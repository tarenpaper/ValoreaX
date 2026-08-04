"""Company endpoints: list, ingest, detail, dashboard summary, refresh."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import or_, select

from app.api.errors import ApiError
from app.api.schemas import IngestRequestSchema
from app.api.serializers import company_to_dict, metric_to_dict
from app.api.v1.helpers import cache_service, get_company_or_404, get_json_body
from app.extensions import db
from app.models import Company
from app.providers.base import CompanyNotFound, ProviderError
from app.providers.mock_provider import MockSecProvider
from app.services import PRIMARY_CONCEPTS, ingest_company
from app.services.derivations import latest_annual_metrics

bp = Blueprint("companies", __name__)


@bp.get("")
def list_companies():
    q = (request.args.get("query") or "").strip()
    stmt = select(Company).order_by(Company.ticker)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Company.ticker.ilike(like), Company.name.ilike(like)))
    companies = db.session.execute(stmt).scalars().all()

    provider = current_app.config.get("SEC_PROVIDER", "mock")
    suggestions = []
    if provider == "mock":
        ingested = {c.ticker for c in companies}
        suggestions = [t for t in MockSecProvider.available_tickers() if t not in ingested]
    return jsonify({
        "companies": [company_to_dict(c, include_counts=True) for c in companies],
        "provider": provider,
        "available_mock_tickers": suggestions,
    })


@bp.post("")
def create_company():
    """Ingest a company by ticker (fetch SEC data, normalize, persist)."""
    body = IngestRequestSchema().load(get_json_body())
    ticker = body["ticker"].upper()
    try:
        result = ingest_company(db.session, ticker, cache_service(), current_app.config)
    except CompanyNotFound as exc:
        raise ApiError(str(exc), status=404, code="not_found") from exc
    except ProviderError as exc:
        raise ApiError(f"Data provider error: {exc}", status=502, code="upstream_error") from exc

    return jsonify({
        "company": company_to_dict(result.company, include_counts=True),
        "ingestion": {
            "provider": result.provider,
            "metric_count": result.metric_count,
            "filing_count": result.filing_count,
            "was_cached": result.was_cached,
            "warnings": result.warnings,
        },
    }), 201


@bp.get("/<identifier>")
def get_company(identifier: str):
    company = get_company_or_404(identifier)
    return jsonify(company_to_dict(company, include_counts=True))


@bp.get("/<identifier>/summary")
def company_summary(identifier: str):
    """Dashboard payload: profile + latest key financials + data-quality warnings."""
    company = get_company_or_404(identifier)
    metrics = latest_annual_metrics(db.session, company.id)
    key = {c: metric_to_dict(metrics[c]) for c in PRIMARY_CONCEPTS if c in metrics}
    latest_fy = next((m.fiscal_year for m in metrics.values() if m.fiscal_year), None)

    warnings = [
        f"{m.concept}: {m.quality_note}"
        for m in metrics.values()
        if m.status in {"missing", "inconsistent"} and m.quality_note
    ]
    return jsonify({
        "company": company_to_dict(company),
        "latest_fiscal_year": latest_fy,
        "key_metrics": key,
        "data_quality_warnings": warnings,
    })


@bp.post("/<identifier>/refresh")
def refresh_company(identifier: str):
    """Re-ingest, bypassing the cache for this company's facts."""
    company = get_company_or_404(identifier)
    cache = cache_service()
    cache.invalidate("company_facts", company.cik or company.ticker)
    try:
        result = ingest_company(db.session, company.ticker, cache, current_app.config)
    except (CompanyNotFound, ProviderError) as exc:
        raise ApiError(f"Refresh failed: {exc}", status=502) from exc
    return jsonify({
        "company": company_to_dict(result.company, include_counts=True),
        "ingestion": {"metric_count": result.metric_count, "warnings": result.warnings},
    })
