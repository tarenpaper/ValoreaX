"""Watchlist aggregation: one compact row per *watched* company.

Membership is explicit and capped, because every watched company needs its own daily price
request and the market-data plan bounds those. Unwatching keeps all stored data, so a
company can leave and rejoin the list without costing a provider call.

Assembles, for every watched company, the fields the watchlist view needs —
latest price + daily change, a short close series for the sparkline, a derived
clinical-status chip from its catalysts, and its most recent signal — so the
frontend renders the table from a single request instead of N per-company calls.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import CatalystEvent, Company, MarketPrice, SignalRun

_SPARK_POINTS = 7


def _price_block(session, company_id: int) -> dict:
    rows = session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company_id).order_by(MarketPrice.date)
    ).scalars().all()
    closes = [r.close for r in rows if r.close is not None]
    latest = closes[-1] if closes else None
    prev = closes[-2] if len(closes) >= 2 else None
    change_pct = round(latest / prev - 1.0, 6) if (latest and prev and prev > 0) else None
    series = closes[-_SPARK_POINTS:]
    change_7d = round(series[-1] / series[0] - 1.0, 6) if len(series) >= 2 and series[0] > 0 else None
    return {"price": latest, "change_pct": change_pct, "change_7d": change_7d, "series": series}


def _clinical_status(session, company_id: int, as_of: date) -> dict:
    cats = session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all()
    pending = [c for c in cats if c.outcome == "pending" and c.expected_date]
    overdue = sorted([c for c in pending if c.expected_date < as_of], key=lambda c: c.expected_date)
    upcoming = sorted([c for c in pending if c.expected_date >= as_of], key=lambda c: c.expected_date)
    resolved = sorted([c for c in cats if c.actual_date], key=lambda c: c.actual_date, reverse=True)

    def label(c, when):
        return f"{c.event_type.replace('_', ' ')} · {when.isoformat()}"

    if overdue:
        c = overdue[0]
        return {"state": "overdue", "label": label(c, c.expected_date), "catalyst_id": c.id}
    if upcoming:
        c = upcoming[0]
        return {"state": "upcoming", "label": label(c, c.expected_date), "catalyst_id": c.id}
    if resolved:
        c = resolved[0]
        return {"state": "recent", "label": f"{c.event_type.replace('_', ' ')} · {c.outcome}",
                "catalyst_id": c.id}
    return {"state": "none", "label": "No catalysts", "catalyst_id": None}


def _latest_signal(session, company_id: int) -> str | None:
    run = session.execute(
        select(SignalRun).where(SignalRun.company_id == company_id).order_by(SignalRun.created_at.desc())
    ).scalars().first()
    return run.signal if run else None


def build_watchlist(session, as_of: date | None = None, owner_id: str | None = None,
                    watched_only: bool = True) -> list[dict]:
    as_of = as_of or date.today()
    stmt = select(Company).where(Company.owner_id == owner_id)
    if watched_only:
        stmt = stmt.where(Company.watched.is_(True))
    companies = session.execute(stmt.order_by(Company.ticker)).scalars().all()
    rows = []
    for c in companies:
        rows.append({
            "id": c.id,
            "ticker": c.ticker,
            "name": c.name,
            "source": c.source,
            "is_example": c.is_example,
            "watched": c.watched,
            **_price_block(session, c.id),
            "clinical_status": _clinical_status(session, c.id, as_of),
            "signal": _latest_signal(session, c.id),
        })
    return rows
