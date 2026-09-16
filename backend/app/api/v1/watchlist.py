"""Watchlist membership and the named baskets that can populate it.

The list is capped: each watched company needs its own daily price request and the
market-data plan bounds those. Removing a company only clears the flag — its filings, drug
models and valuation stay, so a basket swap costs no provider calls after the first load.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.api.schemas import BasketSchema, WatchRequestSchema
from app.api.v1.helpers import cache_service, get_company_or_404, get_json_body
from app.extensions import db
from app.models import Company, WatchlistBasket
from app.services.baskets import MAX_MEMBERS, basket_to_dict, validate_basket_name
from app.services.ingestion_service import ingest_company
from app.services.watchlist import build_watchlist

bp = Blueprint("watchlist", __name__)

DISCLAIMER = "Educational research — not investment advice. Prices/status may be sample data."


def _limit() -> int:
    return current_app.config.get("WATCHLIST_LIMIT", MAX_MEMBERS)


def _owned(ticker: str | None = None) -> list[Company]:
    stmt = select(Company).where(Company.owner_id == g.user_id)
    if ticker:
        stmt = stmt.where(Company.ticker == ticker.upper())
    return db.session.execute(stmt.order_by(Company.ticker)).scalars().all()


def _watched() -> list[Company]:
    return [c for c in _owned() if c.watched]


def _get_basket_or_404(basket_id: int) -> WatchlistBasket:
    basket = db.session.execute(
        select(WatchlistBasket).where(WatchlistBasket.id == basket_id,
                                      WatchlistBasket.owner_id == g.user_id)
    ).scalar_one_or_none()
    if basket is None:
        raise ApiError(f"Basket {basket_id} not found.", status=404)
    return basket


@bp.get("/watchlist")
def get_watchlist():
    rows = build_watchlist(db.session, owner_id=g.user_id)
    limit = _limit()
    return jsonify({
        "count": len(rows),
        "limit": limit,
        # Negative would be misleading; an account already over the cap simply has none left.
        "remaining": max(0, limit - len(rows)),
        "as_of": date.today().isoformat(),
        "companies": rows,
        "disclaimer": DISCLAIMER,
    })


@bp.post("/watchlist")
def watch():
    """Add a ticker to the watchlist, ingesting it only if it has never been stored."""
    ticker = WatchRequestSchema().load(get_json_body())["ticker"].upper()
    existing = next(iter(_owned(ticker)), None)
    if existing is not None and existing.watched:
        return jsonify({"ticker": ticker, "watched": True, "already": True}), 200

    watched = _watched()
    if len(watched) >= _limit():
        raise ApiError(
            f"The watchlist holds {_limit()} companies. Remove one to add {ticker} — "
            f"removing keeps everything already downloaded for it.",
            status=409, code="watchlist_full",
            details={"watching": [c.ticker for c in watched], "limit": _limit()},
        )

    ingested = False
    if existing is None:
        # Never stored: fetch it. Re-watching something already held costs no provider call.
        result = ingest_company(db.session, ticker, cache_service(), current_app.config,
                                owner_id=g.user_id)
        existing = result.company
        ingested = True
    existing.watched = True
    db.session.commit()
    return jsonify({"ticker": existing.ticker, "company_id": existing.id,
                    "watched": True, "ingested": ingested}), 201


@bp.delete("/watchlist/<ticker>")
def unwatch(ticker: str):
    company = get_company_or_404(ticker)
    company.watched = False
    db.session.commit()
    return jsonify({"ticker": company.ticker, "watched": False,
                    "note": "Removed from the watchlist. Its filings, drug models and "
                            "valuation are kept, so adding it back costs no download."})


# --- Baskets -----------------------------------------------------------------------
@bp.get("/baskets")
def list_baskets():
    by_ticker = {c.ticker: c for c in _owned()}
    baskets = db.session.execute(
        select(WatchlistBasket).where(WatchlistBasket.owner_id == g.user_id)
        .order_by(WatchlistBasket.name)
    ).scalars().all()
    return jsonify({
        "count": len(baskets),
        "limit": _limit(),
        "baskets": [basket_to_dict(b, by_ticker) for b in baskets],
    })


@bp.post("/baskets")
def create_basket():
    data = BasketSchema().load(get_json_body())
    tickers = [t.upper() for t in data["tickers"]]
    if len(set(tickers)) != len(tickers):
        raise ApiError("A basket cannot list the same company twice.", status=422)
    if len(tickers) > _limit():
        raise ApiError(f"A basket holds at most {_limit()} companies.", status=422)

    by_ticker = {c.ticker: c for c in _owned()}
    missing = [t for t in tickers if t not in by_ticker]
    if missing:
        raise ApiError(f"Not in your workspace: {', '.join(missing)}. Add them first.",
                       status=422)

    members = [{"ticker": t, "name": by_ticker[t].name} for t in tickers]
    reason = validate_basket_name(data["name"], members)
    if reason:
        raise ApiError(reason, status=422, code="basket_name_mismatch")

    basket = WatchlistBasket(owner_id=g.user_id, name=data["name"].strip().upper())
    basket.set_members(tickers)
    db.session.add(basket)
    try:
        db.session.commit()
    except IntegrityError as exc:  # unique(owner_id, name)
        db.session.rollback()
        raise ApiError(f"You already have a basket called {basket.name}.", status=409) from exc
    return jsonify(basket_to_dict(basket, by_ticker)), 201


@bp.delete("/baskets/<int:basket_id>")
def delete_basket(basket_id: int):
    basket = _get_basket_or_404(basket_id)
    db.session.delete(basket)
    db.session.commit()
    return jsonify({"deleted": True, "id": basket_id,
                    "note": "The basket is gone; its companies are untouched."})


@bp.post("/baskets/<int:basket_id>/activate")
def activate_basket(basket_id: int):
    """Make this basket the watchlist: its members are watched, everything else is not."""
    basket = _get_basket_or_404(basket_id)
    tickers = basket.member_tickers()
    if len(tickers) > _limit():
        raise ApiError(f"{basket.name} holds {len(tickers)} companies but the watchlist "
                       f"takes {_limit()}.", status=422)

    by_ticker = {c.ticker: c for c in _owned()}
    missing = [t for t in tickers if t not in by_ticker]
    if missing:
        raise ApiError(f"{basket.name} names companies no longer in your workspace: "
                       f"{', '.join(missing)}.", status=422, code="basket_incomplete")

    for company in by_ticker.values():
        company.watched = company.ticker in tickers
    db.session.commit()
    return jsonify({"activated": basket.name, "watching": tickers,
                    "basket": basket_to_dict(basket, by_ticker)})
