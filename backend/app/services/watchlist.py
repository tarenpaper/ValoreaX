"""Watchlist aggregation: one compact row per *watched* company.

Membership is explicit and capped, because every watched company needs its own daily price
request and the market-data plan bounds those. Unwatching keeps all stored data, so a
company can leave and rejoin the list without costing a provider call.

Assembles, for every watched company, the fields the watchlist view needs —
latest price + daily change, a short close series for the sparkline, a derived
clinical-status chip from its catalysts, and its most recent signal — so the
frontend renders the table from a single request instead of N per-company calls.

Related rows are loaded in four queries for the whole list, not three per company.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select

from app.models import CatalystEvent, Company, MarketPrice, SignalRun

_SPARK_POINTS = 7


def _price_block(rows) -> dict:
    closes = [r.close for r in rows if r.close is not None]
    latest = closes[-1] if closes else None
    prev = closes[-2] if len(closes) >= 2 else None
    change_pct = round(latest / prev - 1.0, 6) if (latest and prev and prev > 0) else None
    series = closes[-_SPARK_POINTS:]
    change_7d = round(series[-1] / series[0] - 1.0, 6) if len(series) >= 2 and series[0] > 0 else None
    return {"price": latest, "change_pct": change_pct, "change_7d": change_7d, "series": series}


def _clinical_status(cats, as_of: date) -> dict:
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


def build_watchlist(session, as_of: date | None = None, owner_id: str | None = None,
                    watched_only: bool = True) -> list[dict]:
    as_of = as_of or date.today()
    stmt = select(Company).where(Company.owner_id == owner_id)
    if watched_only:
        stmt = stmt.where(Company.watched.is_(True))
    companies = session.execute(stmt.order_by(Company.ticker)).scalars().all()
    ids = [c.id for c in companies]
    if not ids:
        return []

    prices_by: dict[int, list] = defaultdict(list)
    ranked_prices = select(
        MarketPrice.company_id, MarketPrice.date, MarketPrice.close,
        func.row_number().over(partition_by=MarketPrice.company_id,
                               order_by=MarketPrice.date.desc()).label("position"),
    ).where(MarketPrice.company_id.in_(ids), MarketPrice.close.is_not(None)).subquery()
    for row in session.execute(
        select(ranked_prices.c.company_id, ranked_prices.c.date, ranked_prices.c.close)
        .where(ranked_prices.c.position <= _SPARK_POINTS)
        .order_by(ranked_prices.c.company_id, ranked_prices.c.date)
    ):
        prices_by[row.company_id].append(row)

    cats_by: dict[int, list] = defaultdict(list)
    for row in session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id.in_(ids))
    ).scalars():
        cats_by[row.company_id].append(row)

    latest_signal: dict[int, str] = {}
    ranked_signals = select(
        SignalRun.company_id, SignalRun.signal,
        func.row_number().over(
            partition_by=SignalRun.company_id,
            order_by=(SignalRun.created_at.desc(), SignalRun.id.desc()),
        ).label("position"),
    ).where(SignalRun.company_id.in_(ids)).subquery()
    for run in session.execute(
        select(ranked_signals.c.company_id, ranked_signals.c.signal)
        .where(ranked_signals.c.position == 1)
    ):
        latest_signal[run.company_id] = run.signal

    return [{
        "id": c.id,
        "ticker": c.ticker,
        "name": c.name,
        "source": c.source,
        "is_example": c.is_example,
        "watched": c.watched,
        **_price_block(prices_by[c.id]),
        "clinical_status": _clinical_status(cats_by[c.id], as_of),
        "signal": latest_signal.get(c.id),
    } for c in companies]
