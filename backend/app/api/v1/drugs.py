"""Drug models and the sum-of-the-parts valuation built from them."""
from __future__ import annotations

import json

from flask import Blueprint, current_app, jsonify
from marshmallow import EXCLUDE, Schema, fields, validate

from app.api.errors import ApiError
from app.api.schemas import DiscountRateSchema
from app.api.v1.helpers import cache_service, get_company_or_404, get_json_body
from app.extensions import db
from app.models import DrugAsset
from app.providers.factory import get_sec_provider
from app.services.drug_sync import sync_drugs
from app.services.rnpv_benchmarks import EROSION, HORIZON_YEARS
from app.services.rnpv_valuation import value_company

bp = Blueprint("drugs", __name__)


class OverridesSchema(Schema):
    """Per-drug edits. Everything is optional; omitted fields keep the filing's value."""

    class Meta:
        unknown = EXCLUDE

    base_revenue = fields.Float(validate=validate.Range(min=0))
    peak_sales = fields.Float(validate=validate.Range(min=0))
    probability = fields.Float(validate=validate.Range(min=0, max=1))
    launch_year = fields.Integer(validate=validate.Range(min=1990, max=2100))
    years_to_peak = fields.Integer(validate=validate.Range(min=1, max=20))
    loe_year = fields.Integer(validate=validate.Range(min=1990, max=2100))
    growth_rate = fields.Float(validate=validate.Range(min=-1, max=5))
    growth_years = fields.Integer(validate=validate.Range(min=1, max=20))
    modality = fields.String(validate=validate.OneOf(sorted(EROSION)))


class AssetPatchSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    included = fields.Boolean()
    overrides = fields.Nested(OverridesSchema)
    reset_overrides = fields.Boolean(load_default=False)


class ValuationSchema(DiscountRateSchema):
    """The shared rate, plus the projection controls only this endpoint takes."""

    horizon_years = fields.Integer(load_default=HORIZON_YEARS, validate=validate.Range(min=1, max=40))
    include_sensitivity = fields.Boolean(load_default=False)
    # The stand-in for programmes the filing gives no population for. On by default, but it
    # rests on a weaker analog than the rest of the model, so it can be switched off.
    include_continuing_value = fields.Boolean(load_default=True)


def _asset_to_dict(row):
    return {
        "id": row.id, "key": row.key, "name": row.name, "kind": row.kind, "origin": row.origin,
        "indication": row.indication, "phase": row.phase, "modality": row.modality,
        "included": row.included, "xbrl_member": row.xbrl_member,
        "extracted": json.loads(row.extracted) if row.extracted else {},
        "overrides": json.loads(row.overrides) if row.overrides else {},
    }


def _get_asset_or_404(asset_id: int) -> DrugAsset:
    row = db.session.get(DrugAsset, asset_id)
    # Scope through the company, so one account cannot reach another's drugs.
    if row is None or row.company is None:
        raise ApiError(f"Drug {asset_id} not found.", status=404)
    get_company_or_404(str(row.company_id))
    return row


@bp.get("/companies/<identifier>/drugs")
def list_drugs(identifier):
    company = get_company_or_404(identifier)
    return jsonify({
        "company_id": company.id, "ticker": company.ticker,
        "drugs": [_asset_to_dict(row) for row in company.drug_assets],
        "product_revenues": [
            {"member": row.member, "label": row.label, "fiscal_year": row.fiscal_year,
             "value": row.value, "us_value": row.us_value, "classification": row.classification,
             "reason": row.reason, "geography_basis": row.geography_basis,
             "accession_number": row.accession_number}
            for row in company.product_revenues],
    })


@bp.post("/companies/<identifier>/drugs/sync")
def sync(identifier):
    """Rebuild the drug models from the latest 10-K. Skips work when nothing has changed."""
    company = get_company_or_404(identifier)
    force = bool((get_json_body() or {}).get("force"))
    result = sync_drugs(db.session, company, get_sec_provider(), cache_service(),
                        current_app.config, force=force)
    return jsonify({
        "company_id": company.id, "ticker": company.ticker,
        "accession_number": result.accession_number, "skipped": result.skipped,
        "product_lines": result.product_lines, "drugs": result.assets,
        "unvalued": result.unvalued, "warnings": result.warnings or [],
    })


@bp.patch("/drugs/<int:asset_id>")
def update_drug(asset_id):
    row = _get_asset_or_404(asset_id)
    data = AssetPatchSchema().load(get_json_body())
    if data.get("reset_overrides"):
        row.overrides = None
    if "overrides" in data:
        current = json.loads(row.overrides) if row.overrides else {}
        row.overrides = json.dumps({**current, **data["overrides"]})
    if "included" in data:
        row.included = data["included"]
    db.session.commit()
    return jsonify(_asset_to_dict(row))


@bp.post("/companies/<identifier>/valuation")
def valuation(identifier):
    company = get_company_or_404(identifier)
    args = ValuationSchema().load(get_json_body())
    return jsonify(value_company(
        db.session, company, discount_rate=args["discount_rate"],
        horizon=args["horizon_years"], include_sensitivity=args["include_sensitivity"],
        include_continuing_value=args["include_continuing_value"]))
