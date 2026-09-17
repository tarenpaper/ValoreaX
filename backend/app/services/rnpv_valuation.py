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
from dataclasses import asdict

from sqlalchemy import select

from app.models import MarketPrice
from app.services.derivations import latest_annual_metrics
from app.services.drug_assets import CONTINUING_VALUE_ELIGIBLE, ESTABLISHED_YEARS
from app.services.rnpv import Asset, Economics, aggregate, project_asset, sensitivity
from app.services.rnpv_benchmarks import (
    CONTINUING_VALUE_HAIRCUT,
    DEFAULT_COMMERCIAL_COST_RATE,
    DEFAULT_DEVELOPMENT_COST_PER_YEAR,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_GROSS_MARGIN,
    EXCLUSIVITY_YEARS_FROM_LAUNCH,
    HORIZON_YEARS,
    MAX_EFFECTIVE_TAX_RATE,
    US_STATUTORY_TAX_RATE,
    YEARS_TO_PEAK,
    development_cost_for,
)


def _value(metrics, concept):
    metric = metrics.get(concept)
    return metric.value if metric is not None and metric.value is not None and metric.status != "missing" else None


def company_economics(metrics) -> tuple[Economics, dict]:
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

    # Development cost is per programme by phase (see `rnpv_benchmarks`), not a share of
    # the company's R&D budget. R&D beyond the modelled programmes is not subtracted: the
    # model also omits the future programmes it will create.
    sources["development_cost_per_year"] = "benchmark"
    return (Economics(gross_margin, commercial, tax, DEFAULT_DEVELOPMENT_COST_PER_YEAR),
            {"sources": sources, "revenue": revenue, "sga": sga, "research_development": research,
             "research_development_note": (
                 "Reported R&D is shown for context. Each modelled programme is charged the "
                 "published annual cost for its phase instead, and unallocated R&D is not "
                 "subtracted.")})


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
        development_cost_per_year=(development_cost_for(row.phase)
                                   if row.kind == "pipeline" else 0.0),
    )
    provenance = {
        "id": row.id, "key": row.key, "indication": row.indication, "phase": row.phase,
        "origin": row.origin, "included": row.included, "xbrl_member": row.xbrl_member,
        "overrides": sorted(overrides), "values": values, "extracted": extracted,
        "sources": {field: ("override" if field in overrides else default)
                    for field, default in (("base_revenue", "sec"), ("growth_rate", "derived"),
                                           ("peak_sales", "derived"), ("probability", "benchmark"),
                                           ("launch_year", "benchmark"), ("years_to_peak", "benchmark"),
                                           ("loe_year", "sec_quoted"), ("modality", "benchmark"),
                                           ("development_cost_per_year", "benchmark"))},
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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def continuing_value(built, results, economics, discount_rate, start_year, horizon) -> dict:
    """Value the programmes the filing gives no population for, on a weaker analog.

    Most large pharma discloses no patient populations at all — Lilly's 10-K contains none,
    so nine Phase 3 programmes come back worth nothing. That is a gap in disclosure, not in
    the pipeline, and recording it as zero understates those companies systematically.

    The stand-in is the company's own *median* marketed product, halved: a successful
    programme is assumed to sell like a typical drug of this company's, not like its
    flagship. It is still risk-weighted by phase and still ends at a patent cliff, so it is
    a sum of finite drug models rather than a terminal value — and it is reported on its own
    line so drug value stays the number the filings support.

    Programmes excluded for cannibalisation or for having no published success rate get
    nothing: those are real absences of value, not undisclosed ones.
    """
    # Only *established* products, on the same three-year rule the population analog uses.
    # A drug in its launch year earns a fraction of what it eventually will, so including
    # one drags the median far below any plausible peak: Vertex's median across all four
    # products is $0.5B, because Casgevy and Journavx have barely started selling.
    marketed = [asset.base_revenue for asset, provenance in built
                if asset.kind == "marketed" and asset.base_revenue > 0
                and len(provenance["values"].get("years_reported") or []) >= ESTABLISHED_YEARS]
    analog = _median(marketed)
    eligible = [(asset, provenance) for (asset, provenance), result in zip(built, results, strict=True)
                if result.rnpv is None
                and (provenance["values"].get("unvalued_code") in CONTINUING_VALUE_ELIGIBLE)
                and provenance["values"].get("probability") is not None
                # A programme the latest filing no longer names is not undisclosed, it is
                # gone. Its stored code would otherwise still make it eligible.
                and not provenance["values"].get("retired_from_filing")]

    detail = {"value": 0.0, "programmes": [], "abandoned": 0, "analog_peak_sales": analog,
              "basis": "company_median_product", "haircut": CONTINUING_VALUE_HAIRCUT}
    if analog is None or not eligible:
        detail["note"] = (
            "No programme needed a stand-in." if not eligible else
            "This company has no established marketed product to use as an analog, so its "
            "undisclosed programmes stay at no value.")
        return detail

    peak = analog * CONTINUING_VALUE_HAIRCUT
    total = 0.0
    abandoned = 0
    for asset, provenance in eligible:
        stand_in = Asset(**{**asdict(asset), "peak_sales": peak, "unvalued_reason": None})
        result = project_asset(stand_in, economics, discount_rate, start_year, horizon)
        if result.rnpv is None:
            continue
        # A programme worth less than it costs to finish would be discontinued rather than
        # funded to the end, so its downside is bounded at zero. Counting it as negative
        # would also make an undisclosed pipeline *subtract* from a company's value, which
        # is the opposite of what this line exists to correct.
        if result.rnpv <= 0:
            abandoned += 1
            continue
        total += result.rnpv
        detail["programmes"].append({
            "name": asset.name, "phase": provenance.get("phase"),
            "probability": asset.probability, "rnpv": round(result.rnpv, 2),
            "assumed_peak_sales": peak,
        })
    detail["value"] = total
    detail["abandoned"] = abandoned
    dropped = (f" {abandoned} more would cost more to finish than a median drug returns, so "
               f"they are treated as discontinued rather than counted against the company."
               if abandoned else "")
    detail["note"] = (
        f"{len(detail['programmes'])} programme(s) the filing gives no patient population "
        f"for, valued on this company's median marketed product "
        f"(${analog / 1e9:,.1f}B) halved. A weaker basis than a disclosed population, so it "
        f"is kept out of drug value and can be switched off.{dropped}")
    return detail


def value_company(session, company, discount_rate: float = DEFAULT_DISCOUNT_RATE,
                  start_year: int | None = None, horizon: int = HORIZON_YEARS,
                  include_sensitivity: bool = False,
                  include_continuing_value: bool = True) -> dict:
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
    economics, economics_detail = company_economics(metrics)
    overhead = overhead_per_year(metrics, active_assets, economics.commercial_cost_rate)

    liquidity = _value(metrics, "liquidity") or _value(metrics, "cash") or 0.0
    net_cash = liquidity - (_value(metrics, "total_debt") or 0.0)
    shares = _value(metrics, "shares_outstanding")

    results = [project_asset(asset, economics, discount_rate, start_year, horizon)
               for asset in assets]
    continuing = (continuing_value(built, results, economics, discount_rate, start_year, horizon)
                  if include_continuing_value
                  else {"value": 0.0, "programmes": [], "note": "Switched off for this run."})
    outcome = aggregate(results, overhead, net_cash, shares, discount_rate,
                        continuing_value=continuing["value"])

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
        def scenario_continuing_value(scaled, scenario_results, rate):
            # Use the scenario's marketed revenue to derive its analog, then re-project
            # development costs and the abandonment floor at the scenario's discount rate.
            scenario_built = [(asset, provenance) for asset, (_, provenance)
                              in zip(scaled, built, strict=True)]
            return continuing_value(scenario_built, scenario_results, economics, rate,
                                    start_year, horizon)["value"]

        rates = [round(discount_rate + step, 4) for step in (-0.02, -0.01, 0, 0.01, 0.02)]
        grid = sensitivity(assets, economics, overhead, net_cash, shares, start_year,
                           [r for r in rates if r > 0], [0.8, 0.9, 1.0, 1.1, 1.2], horizon,
                           continuing_value_for=(scenario_continuing_value
                                                 if include_continuing_value else None))

    return {
        "company": {"id": company.id, "ticker": company.ticker, "name": company.name},
        "discount_rate": discount_rate, "start_year": start_year, "horizon_years": horizon,
        "assets": outcome.assets, "unvalued": outcome.unvalued, "excluded": excluded,
        "asset_value": outcome.asset_value, "continuing_value": continuing,
        "overhead_present_value": outcome.overhead_present_value,
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
                   "the published probability of reaching market for their phase. Programmes the "
                   "filing gives no patient population for are carried on a separate continuing "
                   "value line, on a weaker analog."),
    }
