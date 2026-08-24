"""News endpoints: composite News-Intelligence view + ingestion from a provider."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.api.errors import ApiError
from app.api.v1.helpers import cache_service, get_company_or_404
from app.extensions import db
from app.providers import ProviderError, get_news_provider
from app.services.news_ingestion import ingest_news
from app.services.news_service import build_news_view

bp = Blueprint("news", __name__)


@bp.get("/companies/<identifier>/news")
def get_news(identifier: str):
    """Composite payload for the News Intelligence page (stream + analytics)."""
    company = get_company_or_404(identifier)
    return jsonify(build_news_view(db.session, company))


@bp.post("/companies/<identifier>/news/ingest")
def ingest_company_news(identifier: str):
    """Fetch news from the configured provider (NEWS_PROVIDER), analyze, and upsert."""
    company = get_company_or_404(identifier)
    provider = get_news_provider()
    try:
        result = ingest_news(db.session, company, provider, cache_service(), current_app.config)
    except ProviderError as exc:
        raise ApiError(f"News provider error: {exc}", status=502, code="upstream_error") from exc

    view = build_news_view(db.session, company)
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "ingestion": {
            "provider": result.provider,
            "fetched": result.fetched,
            "added": result.added,
            "skipped": result.skipped,
            "was_cached": result.was_cached,
            "warnings": result.warnings,
        },
        **view,
    }), 201
