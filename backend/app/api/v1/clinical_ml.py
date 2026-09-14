"""Authenticated clinical ML API; training remains an offline research job."""
from flask import Blueprint, current_app, jsonify

from app.api.errors import ApiError
from app.api.v1.helpers import get_company_or_404
from app.extensions import db
from app.providers.base import ProviderError
from app.services.clinical_ml import ingest, view

bp = Blueprint("clinical_ml", __name__)


@bp.get("/companies/<identifier>/clinical-ml")
def clinical_predictions(identifier):
    company = get_company_or_404(identifier)
    return jsonify(view(db.session, company, current_app.config))


@bp.post("/companies/<identifier>/clinical-ml/ingest")
def ingest_clinical_snapshots(identifier):
    company = get_company_or_404(identifier)
    if current_app.config.get("CATALYST_PROVIDER") != "clinicaltrials":
        raise ApiError("Clinical ML ingestion requires the live ClinicalTrials.gov provider.", status=422)
    try:
        result = ingest(db.session, company, current_app.config)
    except (ProviderError, ValueError) as exc:
        raise ApiError("Clinical trial ingestion failed; please retry.", status=502,
                       code="upstream_error") from exc
    return jsonify({**view(db.session, company, current_app.config), "ingestion": result}), 201
