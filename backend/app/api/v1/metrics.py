"""Financial-metric and filing read endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from app.api.serializers import filing_to_dict, metric_to_dict
from app.api.v1.helpers import get_company_or_404
from app.extensions import db
from app.models import Filing, FinancialMetric

bp = Blueprint("metrics", __name__)


@bp.get("/<identifier>/metrics")
def list_metrics(identifier: str):
    """All normalized metrics for a company, optionally filtered by concept / fiscal year.

    Every row carries source provenance and an extraction status/confidence.
    """
    company = get_company_or_404(identifier)
    stmt = select(FinancialMetric).where(FinancialMetric.company_id == company.id)

    concept = request.args.get("concept")
    if concept:
        stmt = stmt.where(FinancialMetric.concept == concept)
    fy = request.args.get("fiscal_year")
    if fy and fy.isdigit():
        stmt = stmt.where(FinancialMetric.fiscal_year == int(fy))

    stmt = stmt.order_by(FinancialMetric.fiscal_year.desc(), FinancialMetric.concept)
    metrics = db.session.execute(stmt).scalars().all()
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "count": len(metrics),
        "metrics": [metric_to_dict(m) for m in metrics],
    })


@bp.get("/<identifier>/filings")
def list_filings(identifier: str):
    company = get_company_or_404(identifier)
    filings = db.session.execute(
        select(Filing).where(Filing.company_id == company.id).order_by(Filing.period_end.desc())
    ).scalars().all()
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "count": len(filings),
        "filings": [filing_to_dict(f) for f in filings],
    })
