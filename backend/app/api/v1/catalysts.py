"""Clinical/FDA catalyst CRUD (manual entry only in the MVP)."""
from __future__ import annotations

from flask import Blueprint, jsonify
from sqlalchemy import select

from app.api.errors import ApiError
from app.api.schemas import CatalystCreateSchema, CatalystUpdateSchema
from app.api.serializers import catalyst_to_dict
from app.api.v1.helpers import get_company_or_404, get_json_body
from app.extensions import db
from app.models import CatalystEvent

bp = Blueprint("catalysts", __name__)


def _get_catalyst_or_404(catalyst_id: int) -> CatalystEvent:
    c = db.session.get(CatalystEvent, catalyst_id)
    if c is None:
        raise ApiError(f"Catalyst {catalyst_id} not found.", status=404)
    return c


@bp.get("/companies/<identifier>/catalysts")
def list_catalysts(identifier: str):
    company = get_company_or_404(identifier)
    events = db.session.execute(
        select(CatalystEvent)
        .where(CatalystEvent.company_id == company.id)
        .order_by(CatalystEvent.expected_date)
    ).scalars().all()
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "count": len(events),
        "catalysts": [catalyst_to_dict(c) for c in events],
    })


@bp.post("/companies/<identifier>/catalysts")
def create_catalyst(identifier: str):
    company = get_company_or_404(identifier)
    data = CatalystCreateSchema().load(get_json_body())
    event = CatalystEvent(company_id=company.id, source="manual", **data)
    db.session.add(event)
    db.session.commit()
    return jsonify(catalyst_to_dict(event)), 201


@bp.get("/catalysts/<int:catalyst_id>")
def get_catalyst(catalyst_id: int):
    return jsonify(catalyst_to_dict(_get_catalyst_or_404(catalyst_id)))


@bp.patch("/catalysts/<int:catalyst_id>")
def update_catalyst(catalyst_id: int):
    event = _get_catalyst_or_404(catalyst_id)
    data = CatalystUpdateSchema().load(get_json_body())
    if not data:
        raise ApiError("No updatable fields supplied.", status=400)
    for key, value in data.items():
        setattr(event, key, value)
    db.session.commit()
    return jsonify(catalyst_to_dict(event))


@bp.delete("/catalysts/<int:catalyst_id>")
def delete_catalyst(catalyst_id: int):
    event = _get_catalyst_or_404(catalyst_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({"deleted": True, "id": catalyst_id})
