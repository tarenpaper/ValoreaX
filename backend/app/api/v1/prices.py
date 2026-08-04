"""Market-price endpoints and benchmark-adjusted event returns."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import delete, select

from app.api.errors import ApiError
from app.api.serializers import price_to_dict
from app.api.v1.helpers import get_company_or_404
from app.extensions import db
from app.models import BenchmarkPrice, CatalystEvent, MarketPrice
from app.providers import ProviderError, get_market_provider
from app.services.derivations import event_window_abnormal_return

bp = Blueprint("prices", __name__)


def _benchmark_symbol() -> str:
    return current_app.config["MARKET_BENCHMARK_TICKER"].upper()


@bp.get("/<identifier>/prices")
def list_prices(identifier: str):
    company = get_company_or_404(identifier)
    benchmark = _benchmark_symbol()
    prices = db.session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company.id).order_by(MarketPrice.date)
    ).scalars().all()
    benchmark_prices = db.session.execute(
        select(BenchmarkPrice).where(BenchmarkPrice.symbol == benchmark).order_by(BenchmarkPrice.date)
    ).scalars().all()
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "count": len(prices),
        "prices": [price_to_dict(price) for price in prices],
        "benchmark": {
            "symbol": benchmark,
            "count": len(benchmark_prices),
            "prices": [price_to_dict(price) for price in benchmark_prices],
        },
    })


@bp.post("/<identifier>/prices/sync")
def sync_prices(identifier: str):
    """Refresh issuer and benchmark closes from the configured market-data provider."""
    company = get_company_or_404(identifier)
    provider = get_market_provider()
    benchmark = _benchmark_symbol()
    lookback_days = current_app.config["MARKET_PRICE_LOOKBACK_DAYS"]
    try:
        company_points = provider.get_prices(company.ticker, lookback_days=lookback_days)
        benchmark_points = provider.get_prices(benchmark, lookback_days=lookback_days)
    except ProviderError as exc:
        raise ApiError(str(exc), status=502, code="upstream_error") from exc

    db.session.execute(delete(MarketPrice).where(MarketPrice.company_id == company.id))
    db.session.execute(delete(BenchmarkPrice).where(BenchmarkPrice.symbol == benchmark))
    for point in company_points:
        db.session.add(MarketPrice(
            company_id=company.id,
            date=point.date,
            close=point.close,
            volume=point.volume,
            source=provider.name,
        ))
    for point in benchmark_points:
        db.session.add(BenchmarkPrice(
            symbol=benchmark,
            date=point.date,
            close=point.close,
            volume=point.volume,
            source=provider.name,
        ))
    db.session.commit()

    is_sample = provider.name == "mock"
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "benchmark": benchmark,
        "synced": len(company_points),
        "benchmark_synced": len(benchmark_points),
        "source": provider.name,
        "is_sample": is_sample,
        "note": (
            "Synthetic sample prices — not real market data."
            if is_sample
            else "Recent daily closing prices; not a total-return series."
        ),
    }), 201


@bp.get("/<identifier>/prices/abnormal-return")
def get_abnormal_return(identifier: str):
    """Return a close-to-close issuer excess return for a catalyst/event date."""
    company = get_company_or_404(identifier)
    raw_event_date = request.args.get("event_date")
    if raw_event_date:
        try:
            event_date = date.fromisoformat(raw_event_date)
        except ValueError as exc:
            raise ApiError("event_date must use YYYY-MM-DD format.", status=422) from exc
    else:
        latest = db.session.execute(
            select(CatalystEvent).where(
                CatalystEvent.company_id == company.id,
                CatalystEvent.actual_date.is_not(None),
            ).order_by(CatalystEvent.actual_date.desc())
        ).scalars().first()
        if latest is None or latest.actual_date is None:
            raise ApiError(
                "Provide event_date or add a catalyst with an actual_date first.",
                status=422,
            )
        event_date = latest.actual_date

    window = current_app.config["MARKET_EVENT_WINDOW_TRADING_DAYS"]
    result = event_window_abnormal_return(
        db.session,
        company.id,
        _benchmark_symbol(),
        event_date,
        window_trading_days=window,
    )
    if result is None:
        raise ApiError(
            "Insufficient aligned issuer and benchmark prices for that event window. "
            "Sync recent prices or select a more recent event.",
            status=422,
        )
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        **result,
        "disclaimer": (
            "Educational research metric only. This is a close-to-close excess return, "
            "not investment advice, a total return, or a market-model alpha."
        ),
    })
