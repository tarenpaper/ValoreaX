"""Bridge stored data → engine inputs.

These helpers assemble DCF inputs and signal inputs from normalized metrics,
catalysts, and price history. Market-return helpers use only price observations
available on or before the requested endpoint and never label a raw return as an
abnormal return without subtracting the configured benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.models import BenchmarkPrice, CatalystEvent, FinancialMetric, MarketPrice
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
        metric = metrics.get(concept)
        return metric.value if (metric and metric.value is not None) else None

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

    fiscal_year = next((m.fiscal_year for m in metrics.values() if m.fiscal_year is not None), None)
    return DerivedDcfInputs(
        inputs=DcfInputs(base_revenue=base_revenue, net_debt=net_debt, shares_outstanding=shares_out),
        sources=sources, fiscal_year=fiscal_year, warnings=warnings,
    )


def estimate_cash_runway_quarters(session, company_id: int) -> float | None:
    """cash / quarterly operating burn. None when the company is operating-profitable."""
    metrics = latest_annual_metrics(session, company_id)
    cash = metrics.get("cash")
    operating_income = metrics.get("operating_income")
    if not cash or cash.value is None or not operating_income or operating_income.value is None:
        return None
    if operating_income.value >= 0:
        return None
    quarterly_burn = -operating_income.value / 4.0
    if quarterly_burn <= 0:
        return None
    return round(cash.value / quarterly_burn, 2)


def _aligned_closes(session, company_id: int, benchmark_symbol: str) -> list[tuple[date, float, float]]:
    """Return dates where both the issuer and benchmark have a valid close."""
    company_rows = session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company_id)
    ).scalars().all()
    benchmark_rows = session.execute(
        select(BenchmarkPrice).where(BenchmarkPrice.symbol == benchmark_symbol.upper())
    ).scalars().all()
    company_by_date = {row.date: row.close for row in company_rows if row.close > 0}
    benchmark_by_date = {row.date: row.close for row in benchmark_rows if row.close > 0}
    return [
        (observed_on, company_by_date[observed_on], benchmark_by_date[observed_on])
        for observed_on in sorted(set(company_by_date) & set(benchmark_by_date))
    ]


def _return(start: float, end: float) -> float | None:
    if start <= 0:
        return None
    return end / start - 1.0


def event_window_abnormal_return(
    session,
    company_id: int,
    benchmark_symbol: str,
    event_date: date,
    window_trading_days: int = 5,
) -> dict | None:
    """Calculate close-to-close benchmark-adjusted return around a dated event.

    The window begins at the close immediately preceding the first trading session
    on or after ``event_date`` and ends ``window_trading_days`` sessions later.
    This captures the event-day move plus the following sessions. The calculation
    is a simple excess return (issuer return minus benchmark return), not a
    market-model alpha or total-return series.
    """
    if window_trading_days < 1:
        raise ValueError("window_trading_days must be at least 1")
    aligned = _aligned_closes(session, company_id, benchmark_symbol)
    event_index = next((i for i, row in enumerate(aligned) if row[0] >= event_date), None)
    if event_index is None or event_index == 0:
        return None
    exit_index = event_index + window_trading_days
    if exit_index >= len(aligned):
        return None

    start_date, start_company, start_benchmark = aligned[event_index - 1]
    end_date, end_company, end_benchmark = aligned[exit_index]
    company_return = _return(start_company, end_company)
    benchmark_return = _return(start_benchmark, end_benchmark)
    if company_return is None or benchmark_return is None:
        return None
    abnormal_return = company_return - benchmark_return
    return {
        "event_date": event_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "window_trading_days": window_trading_days,
        "benchmark": benchmark_symbol.upper(),
        "company_return": round(company_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "abnormal_return": round(abnormal_return, 6),
        "methodology": "close-to-close issuer return minus benchmark return",
    }


def trailing_benchmark_adjusted_return(
    session,
    company_id: int,
    benchmark_symbol: str,
    lookback_trading_days: int = 20,
) -> dict | None:
    """Calculate a recent benchmark-adjusted return when no resolved catalyst exists."""
    if lookback_trading_days < 1:
        raise ValueError("lookback_trading_days must be at least 1")
    aligned = _aligned_closes(session, company_id, benchmark_symbol)
    if len(aligned) <= lookback_trading_days:
        return None
    start_date, start_company, start_benchmark = aligned[-(lookback_trading_days + 1)]
    end_date, end_company, end_benchmark = aligned[-1]
    company_return = _return(start_company, end_company)
    benchmark_return = _return(start_benchmark, end_benchmark)
    if company_return is None or benchmark_return is None:
        return None
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "window_trading_days": lookback_trading_days,
        "benchmark": benchmark_symbol.upper(),
        "company_return": round(company_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "abnormal_return": round(company_return - benchmark_return, 6),
        "methodology": "trailing close-to-close issuer return minus benchmark return",
    }


def latest_catalyst_abnormal_return(
    session,
    company_id: int,
    benchmark_symbol: str,
    as_of: date,
    window_trading_days: int = 5,
) -> dict | None:
    """Return the latest fully observable resolved-catalyst excess return."""
    resolved = session.execute(
        select(CatalystEvent).where(
            CatalystEvent.company_id == company_id,
            CatalystEvent.actual_date.is_not(None),
            CatalystEvent.actual_date <= as_of,
            CatalystEvent.outcome != "pending",
        )
    ).scalars().all()
    resolved.sort(key=lambda catalyst: catalyst.actual_date or date.min, reverse=True)
    for catalyst in resolved:
        result = event_window_abnormal_return(
            session, company_id, benchmark_symbol, catalyst.actual_date, window_trading_days
        )
        if result is not None:
            result["catalyst_id"] = catalyst.id
            result["catalyst_event_type"] = catalyst.event_type
            return result
    return None


def next_catalyst_context(session, company_id: int, as_of: date | None = None) -> dict:
    """Return outcome/event_type/days_to_next for the signal engine."""
    as_of = as_of or date.today()
    catalysts = session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all()

    resolved = [c for c in catalysts if c.outcome and c.outcome != "pending"]
    resolved.sort(key=lambda c: c.actual_date or c.expected_date or date.min, reverse=True)
    upcoming = [
        c for c in catalysts
        if c.outcome == "pending" and c.expected_date and c.expected_date >= as_of
    ]
    upcoming.sort(key=lambda c: c.expected_date)

    outcome = resolved[0].outcome if resolved else ("pending" if upcoming else None)
    event_type = resolved[0].event_type if resolved else (upcoming[0].event_type if upcoming else None)
    days_to_next = (upcoming[0].expected_date - as_of).days if upcoming else None
    return {"catalyst_outcome": outcome, "event_type": event_type, "days_to_next_catalyst": days_to_next}
