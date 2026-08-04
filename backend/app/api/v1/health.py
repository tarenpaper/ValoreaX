"""Health and metadata endpoints."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.providers.mock_provider import MockSecProvider

bp = Blueprint("health", __name__)

DISCLAIMER = (
    "ValoreaX is an educational research tool. Outputs are not investment advice, "
    "not guaranteed returns, and may rely on clearly-labelled sample data. "
    "Always verify figures against primary SEC filings."
)


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.get("/meta")
def meta():
    provider = current_app.config.get("SEC_PROVIDER", "mock")
    return jsonify({
        "provider": provider,
        "disclaimer": DISCLAIMER,
        "available_mock_tickers": MockSecProvider.available_tickers() if provider == "mock" else [],
        "cache_ttl_company_facts_s": current_app.config.get("CACHE_TTL_COMPANY_FACTS"),
    })
