"""Shared helpers for the v1 API blueprints."""
from __future__ import annotations

from flask import g, request
from sqlalchemy import select

from app.api.errors import ApiError
from app.extensions import db
from app.models import Company
from app.services import CacheService


def get_json_body() -> dict:
    """Return the parsed JSON body, or {} for an empty body; 400 on malformed JSON."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("Request body must be valid JSON.", status=400)
    if not isinstance(body, dict):
        raise ApiError("Request body must be a JSON object.", status=400)
    return body


def get_company_or_404(identifier: str) -> Company:
    """Resolve a company by numeric id or (case-insensitive) ticker."""
    stmt = (
        select(Company).where(Company.id == int(identifier))
        if str(identifier).isdigit()
        else select(Company).where(Company.ticker == str(identifier).upper())
    )
    company = db.session.execute(stmt.where(Company.owner_id == g.user_id)).scalar_one_or_none()
    if company is None:
        raise ApiError(f"Company {identifier!r} not found. Ingest it first via POST /companies.",
                       status=404)
    return company


def cache_service() -> CacheService:
    return CacheService(db.session)
