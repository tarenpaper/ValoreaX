"""Market-price endpoints (synthetic sample data in the MVP)."""
from __future__ import annotations

from flask import Blueprint, jsonify
from sqlalchemy import delete, select

from app.api.serializers import price_to_dict
from app.api.v1.helpers import get_company_or_404
from app.extensions import db
from app.models import MarketPrice
from app.providers import get_market_provider

bp = Blueprint("prices", __name__)


@bp.get("/<identifier>/prices")
def list_prices(identifier: str):
    company = get_company_or_404(identifier)
    prices = db.session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company.id).order_by(MarketPrice.date)
    ).scalars().all()
    return jsonify({
        "company_id": company.id, "ticker": company.ticker,
        "count": len(prices), "prices": [price_to_dict(p) for p in prices],
    })


@bp.post("/<identifier>/prices/sync")
def sync_prices(identifier: str):
    """(Re)populate the synthetic price series used for abnormal-return inputs."""
    company = get_company_or_404(identifier)
    provider = get_market_provider()
    points = provider.get_prices(company.ticker)

    db.session.execute(delete(MarketPrice).where(MarketPrice.company_id == company.id))
    for p in points:
        db.session.add(MarketPrice(
            company_id=company.id, date=p.date, close=p.close, volume=p.volume, source=provider.name,
        ))
    db.session.commit()
    return jsonify({
        "company_id": company.id, "ticker": company.ticker,
        "synced": len(points), "source": provider.name,
        "note": "Synthetic sample prices — not real market data.",
    }), 201
