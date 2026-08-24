"""Analyst-coverage endpoints: read stored consensus + ratings, and ingest from a provider."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from sqlalchemy import select

from app.api.errors import ApiError
from app.api.serializers import analyst_consensus_to_dict, analyst_rating_to_dict
from app.api.v1.helpers import cache_service, get_company_or_404
from app.extensions import db
from app.models import AnalystRating
from app.providers import ProviderError, get_analyst_provider
from app.services.analyst_ingestion import ingest_analyst_data

bp = Blueprint("analysts", __name__)

DISCLAIMER = (
    "Analyst ratings and price targets are third-party opinions, not facts or advice. "
    "Consensus is a transparent aggregate; verify against primary research."
)


def _ratings_for(company_id: int) -> list:
    return db.session.execute(
        select(AnalystRating)
        .where(AnalystRating.company_id == company_id)
        .order_by(AnalystRating.rating_date.desc())
    ).scalars().all()


@bp.get("/companies/<identifier>/analysts")
def get_analysts(identifier: str):
    company = get_company_or_404(identifier)
    ratings = _ratings_for(company.id)
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "consensus": analyst_consensus_to_dict(company.analyst_consensus),
        "ratings": [analyst_rating_to_dict(r) for r in ratings],
        "disclaimer": DISCLAIMER,
    })


@bp.post("/companies/<identifier>/analysts/ingest")
def ingest_analysts(identifier: str):
    """Fetch analyst coverage from the configured provider (ANALYST_PROVIDER) and upsert it."""
    company = get_company_or_404(identifier)
    provider = get_analyst_provider()
    try:
        result = ingest_analyst_data(
            db.session, company, provider, cache_service(), current_app.config
        )
    except ProviderError as exc:
        raise ApiError(f"Analyst provider error: {exc}", status=502, code="upstream_error") from exc

    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "ingestion": {
            "provider": result.provider,
            "analyst_count": result.analyst_count,
            "rating_rows": result.rating_rows,
            "consensus_label": result.consensus_label,
            "target_consensus": result.target_consensus,
            "implied_upside": result.implied_upside,
            "was_cached": result.was_cached,
            "warnings": result.warnings,
        },
        "consensus": analyst_consensus_to_dict(company.analyst_consensus),
        "ratings": [analyst_rating_to_dict(r) for r in _ratings_for(company.id)],
        "disclaimer": DISCLAIMER,
    }), 201
