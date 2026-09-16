"""Value a company from its stored drugs and its SEC cost structure.

The engine in `rnpv.py` is pure; this module supplies it with real inputs: each drug's
extracted values merged with any overrides, and the company's own margins, tax rate and
balance sheet from normalized SEC metrics.

Every input carries a provenance label so the dashboard can show where a number came from:
`sec` (reported), `sec_quoted` (quoted from the filing text), `derived`, `benchmark`, or
`override`.
"""
from __future__ import annotations

import json
import math

from sqlalchemy import select
from app.models import MarketPrice

from app.services.derivations import latest_annual_metrics
from app.services.rnpv import Asset, Economics, aggregate, project_asset, sensitivity
from app.services.rnpv_benchmarks import (
    DEFAULT_COMMERCIAL_COST_RATE,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_GROSS_MARGIN,
    EXCLUSIVITY_YEARS_FROM_LAUNCH,
    HORIZON_YEARS,
    MAX_EFFECTIVE_TAX_RATE,
    US_STATUTORY_TAX_RATE,
    YEARS_TO_PEAK,
)


def _value(metrics, concept):
    metric = metrics.get(concept)
    return metric.value if metric is not None and metric.value is not None and metric.status != "missing" else None


def company_economics(metrics, pipeline_count: int) -> tuple[Economics, dict]:
    """Cost structure from SEC metrics, with a provenance note per input."""
    revenue = _value(metrics, "revenue") or 0.0
    cost_of_revenue = _value(metrics, "cost_of_revenue")
    sga = _value(metrics, "sga")
    research = _value(metrics, "research_development") or 0.0
    tax_expense = _value(metrics, "income_tax_expense")
    pretax = _value(metrics, "pretax_income")

    sources = {}
    if revenue > 0 and cost_of_revenue is not None:
        gross_margin = max(0.0, min(0.95, 1 - cost_of_revenue / revenue))
        sources["gross_margin"] = "derived"
    else:
        gross_margin = DEFAULT_GROSS_MARGIN
        sources["gross_margin"] = "benchmark"

    if revenue > 0 and sga is not None:
        commercial = max(0.0, min(0.6, sga / revenue))
        sources["commercial_cost_rate"] = "derived"
    else:
        commercial = DEFAULT_COMMERCIAL_COST_RATE
        sources["commercial_cost_rate"] = "benchmark"

    if pretax and pretax > 0 and tax_expense is not None:
        tax = max(0.0, min(MAX_EFFECTIVE_TAX_RATE, tax_expense / pretax))
        sources["tax_rate"] = "derived"
    else:
        tax = US_STATUTORY_TAX_RATE
        sources["tax_rate"] = "benchmark"

    development = research / max(1, pipeline_count) if research else 0.0
    sources["development_cost_per_year"] = "derived" if development else "benchmark"
    return (Economics(gross_margin, commercial, tax, development),
            {"sources": sources, "revenue": revenue, "sga": sga, "research_development": research})


def overhead_per_year(metrics, assets: list[Asset], commercial_rate: float) -> float:
    """Corporate overhead: selling and admin spending not already charged to a drug."""
    sga = _value(metrics, "sga") or 0.0
    allocated = sum(a.base_revenue for a in assets if a.kind == "marketed") * commercial_rate
    return max(0.0, sga - allocated)


def _merged(row) -> dict:
    extracted = json.loads(row.extracted) if row.extracted else {}
    overrides = json.loads(row.overrides) if row.overrides else {}
    return {**extracted, **overrides}, extracted, overrides


def build_asset(row, start_year: int) -> tuple[Asset, dict]:
    """One stored drug as an engine input, plus the provenance of each value."""
    values, extracted, overrides = _merged(row)
    reason = values.get("unvalued_reason")
    # An explicit user estimate can supply what extraction could not derive.
    if row.kind == "pipeline" and {"peak_sales", "probability"} & overrides.keys():
        reason = None
    if values.get("retired_from_filing"):
        reason = "This asset is absent from the latest successfully processed filing."
    launch_year = values.get("launch_year") or start_year
    loe_year = values.get("loe_year")
    assumed_loe = False
    if row.kind == "pipeline":
        if values.get("peak_sales") is None:
            reason = reason or "No peak sales could be derived for this programme."
        if values.get("probability") is None:
            reason = reason or "No published success rate applies to this stage."
        if loe_year is None:
            # A drug still in development has no patent table entry. Holding sales flat to
            # the end of the horizon instead would be a perpetual-value assumption.
            loe_year = launch_year + EXCLUSIVITY_YEARS_FROM_LAUNCH
            assumed_loe = True
    asset = Asset(
        name=row.name, kind=row.kind,
        base_revenue=values.get("base_revenue") or 0.0,
        peak_sales=values.get("peak_sales"),
        launch_year=launch_year,
        years_to_peak=values.get("years_to_peak") or YEARS_TO_PEAK,
        loe_year=loe_year,
        probability=values.get("probability") if values.get("probability") is not None else 1.0,
        growth_rate=values.get("growth_rate") or 0.0,
        growth_years=values.get("growth_years") or 3,
        modality=values.get("modality") or row.modality,
        unvalued_reason=reason,
        base_revenue_year=values.get("fiscal_year"),
    )
    provenance = {
        "id": row.id, "key": row.key, "indication": row.indication, "phase": row.phase,
        "origin": row.origin, "included": row.included, "xbrl_member": row.xbrl_member,
        "overrides": sorted(overrides), "values": values, "extracted": extracted,
        "sources": {field: ("override" if field in overrides else default)
                    for field, default in (("base_revenue", "sec"), ("growth_rate", "derived"),
                                           ("peak_sales", "derived"), ("probability", "benchmark"),
                                           ("launch_year", "benchmark"), ("years_to_peak", "benchmark"),
                                           ("loe_year", "sec_quoted"), ("modality", "benchmark"))},
    }
    if assumed_loe:
        provenance["sources"]["loe_year"] = "benchmark"
        provenance["loe_note"] = (
            f"The filing states no expiry for a drug still in development, so exclusivity is "
            f"assumed to run {EXCLUSIVITY_YEARS_FROM_LAUNCH} years from launch, to "
            f"{asset.loe_year}.")
    elif asset.loe_year is None:
        provenance["loe_note"] = ("No exclusivity date was found in the filing, so sales are held "
                                  "flat to the end of the projection.")
    return asset, provenance


def value_company(session, company, discount_rate: float = DEFAULT_DISCOUNT_RATE,
                  start_year: int | None = None, horizon: int = HORIZON_YEARS,
                  include_sensitivity: bool = True) -> dict:
    """Sum-of-the-parts rNPV for one company, with its inputs and their provenance."""
    from datetime import date

    start_year = start_year or date.today().year
    metrics = latest_annual_metrics(session, company.id)
    rows = [row for row in company.drug_assets if row.included]
    excluded = [row.name for row in company.drug_assets if not row.included]

    built = [build_asset(row, start_year) for row in rows]
    assets = [asset for asset, _ in built]
    active_assets = [asset for asset, provenance in built
                     if not provenance["values"].get("retired_from_filing")]
    pipeline_count = sum(1 for a in active_assets if a.kind == "pipeline")
    economics, economics_detail = company_economics(metrics, pipeline_count)
    overhead = overhead_per_year(metrics, active_assets, economics.commercial_cost_rate)

    liquidity = _value(metrics, "liquidity") or _value(metrics, "cash") or 0.0
    net_cash = liquidity - (_value(metrics, "total_debt") or 0.0)
    shares = _value(metrics, "shares_outstanding")

    results = [project_asset(asset, economics, discount_rate, start_year, horizon)
               for asset in assets]
    outcome = aggregate(results, overhead, net_cash, shares, discount_rate)

    # Match by position, not name: the same drug appears once per indication, and
    # `aggregate` keeps valued and unvalued drugs in their original order.
    valued_positions = [i for i, r in enumerate(results) if r.rnpv is not None]
    unvalued_positions = [i for i, r in enumerate(results) if r.rnpv is None]
    for entry, position in zip(outcome.assets, valued_positions, strict=True):
        entry["provenance"] = built[position][1]
    for entry, position in zip(outcome.unvalued, unvalued_positions, strict=True):
        entry["provenance"] = built[position][1]

    quote = session.execute(select(MarketPrice).where(
        MarketPrice.company_id == company.id, MarketPrice.date <= date.today()
    ).order_by(MarketPrice.date.desc()).limit(1)).scalar_one_or_none()
    current_price = quote.close if quote and math.isfinite(quote.close) and quote.close > 0 else None
    price_to_sotp = (current_price / outcome.value_per_share
                     if current_price is not None and outcome.value_per_share is not None
                     and math.isfinite(outcome.value_per_share) and outcome.value_per_share > 0 else None)

    grid = None
    if include_sensitivity and outcome.equity_value is not None:
        rates = [round(discount_rate + step, 4) for step in (-0.02, -0.01, 0, 0.01, 0.02)]
        grid = sensitivity(assets, economics, overhead, net_cash, shares, start_year,
                           [r for r in rates if r > 0], [0.8, 0.9, 1.0, 1.1, 1.2], horizon)

    return {
        "company": {"id": company.id, "ticker": company.ticker, "name": company.name},
        "discount_rate": discount_rate, "start_year": start_year, "horizon_years": horizon,
        "assets": outcome.assets, "unvalued": outcome.unvalued, "excluded": excluded,
        "asset_value": outcome.asset_value, "overhead_present_value": outcome.overhead_present_value,
        "overhead_per_year": overhead, "net_cash": net_cash, "equity_value": outcome.equity_value,
        "value_per_share": outcome.value_per_share, "shares_outstanding": shares,
        "current_price": current_price,
        "price_as_of": quote.date.isoformat() if quote else None,
        "price_source": quote.source if quote else None,
        "price_to_sotp": price_to_sotp,
        "note": outcome.note, "economics": {**economics_detail, **economics.__dict__},
        "sensitivity": grid,
        "method": ("Each drug is valued on its own: sales ramp to peak, hold, then erode when "
                   "exclusivity ends. There is no terminal value. Pipeline drugs are weighted by "
                   "the published probability of reaching market for their phase."),
    }
