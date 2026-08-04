"""Bridge stored data → engine inputs.

These helpers assemble DCF inputs and signal inputs from the normalized metrics,
catalysts, and (synthetic) price history already in the database — clearly
marking which values are SEC-derived vs. defaulted, so the API can distinguish
data-backed inputs from assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.models import CatalystEvent, FinancialMetric, MarketPrice
from app.services.valuation import DcfInputs


def latest_annual_metrics(session, company_id: int) -> dict[str, FinancialMetric]:
    """Return {concept: metric} for the most recent fiscal year on file."""
    rows = session.execute(
        select(FinancialMetric).where(FinancialMetric.company_id == company_id)
    ).scalars().all()
    if not rows:
        return {}
    latest_fy = max((m.fiscal_year for m in rows if m.fiscal_year is not None), default=None)
    return {m.concept: m for m in rows if m.fiscal_year == latest_fy}


@dataclass
class DerivedDcfInputs:
    inputs: DcfInputs
    sources: dict[str, str]   # concept -> "sec" | "default"
    fiscal_year: int | None
    warnings: list[str]


def derive_dcf_inputs(session, company_id: int, overrides: dict | None = None) -> DerivedDcfInputs:
    """Build DcfInputs from stored metrics, applying any explicit overrides."""
    overrides = overrides or {}
    metrics = latest_annual_metrics(session, company_id)
    warnings: list[str] = []
    sources: dict[str, str] = {}

    def value_of(concept: str):
        m = metrics.get(concept)
        return m.value if (m and m.value is not None) else None

    revenue = value_of("revenue")
    cash = value_of("cash")
    debt = value_of("total_debt")
    shares = value_of("shares_outstanding")

    base_revenue = overrides.get("base_revenue", revenue)
    sources["base_revenue"] = "override" if "base_revenue" in overrides else ("sec" if revenue else "default")
    if base_revenue is None:
        base_revenue = 0.0
        warnings.append("Revenue not available; base_revenue defaulted to 0 (supply an override).")

    if "net_debt" in overrides:
        net_debt = overrides["net_debt"]
        sources["net_debt"] = "override"
    else:
        net_debt = (debt or 0.0) - (cash or 0.0)
        sources["net_debt"] = "sec" if (debt is not None or cash is not None) else "default"
        if debt is None:
            warnings.append("Total debt not available; treated as 0 in net-debt.")
        if cash is None:
            warnings.append("Cash not available; treated as 0 in net-debt.")

    shares_out = overrides.get("shares_outstanding", shares)
    sources["shares_outstanding"] = (
        "override" if "shares_outstanding" in overrides else ("sec" if shares else "default")
    )
    if not shares_out:
        shares_out = 1.0
        warnings.append("Shares outstanding not available; defaulted to 1 (supply an override).")

    fy = next((m.fiscal_year for m in metrics.values() if m.fiscal_year is not None), None)
    return DerivedDcfInputs(
        inputs=DcfInputs(base_revenue=base_revenue, net_debt=net_debt, shares_outstanding=shares_out),
        sources=sources, fiscal_year=fy, warnings=warnings,
    )


def estimate_cash_runway_quarters(session, company_id: int) -> float | None:
    """cash / quarterly operating burn. None when the company is operating-profitable."""
    metrics = latest_annual_metrics(session, company_id)
    cash = metrics.get("cash")
    oi = metrics.get("operating_income")
    if not cash or cash.value is None or not oi or oi.value is None:
        return None
    if oi.value >= 0:
        return None  # profitable: runway not a constraint
    quarterly_burn = -oi.value / 4.0
    if quarterly_burn <= 0:
        return None
    return round(cash.value / quarterly_burn, 2)


def trailing_return_proxy(session, company_id: int, lookback_days: int = 120) -> float | None:
    """Benchmark-naive trailing return over stored prices (proxy for abnormal return).

    Labelled a *proxy* because we do not yet subtract a market/sector benchmark.
    """
    prices = session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company_id).order_by(MarketPrice.date)
    ).scalars().all()
    if len(prices) < 2:
        return None
    window = prices[-lookback_days:] if len(prices) > lookback_days else prices
    first, last = window[0].close, window[-1].close
    if not first:
        return None
    return round(last / first - 1.0, 4)


def next_catalyst_context(session, company_id: int, as_of: date | None = None) -> dict:
    """Return outcome/event_type/days_to_next for the signal engine.

    Prefers the most recently resolved catalyst for a directional outcome; also
    reports days to the nearest upcoming *pending* catalyst (proximity).
    """
    as_of = as_of or date.today()
    catalysts = session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all()

    resolved = [c for c in catalysts if c.outcome and c.outcome != "pending"]
    resolved.sort(key=lambda c: c.actual_date or c.expected_date or date.min, reverse=True)

    upcoming = [c for c in catalysts if c.outcome == "pending" and c.expected_date and c.expected_date >= as_of]
    upcoming.sort(key=lambda c: c.expected_date)

    outcome = resolved[0].outcome if resolved else ("pending" if upcoming else None)
    event_type = (resolved[0].event_type if resolved else (upcoming[0].event_type if upcoming else None))
    days_to_next = (upcoming[0].expected_date - as_of).days if upcoming else None
    return {"catalyst_outcome": outcome, "event_type": event_type, "days_to_next_catalyst": days_to_next}
