"""Valuation endpoint: base/bull/bear DCF + sensitivity, with clear input provenance."""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify

from app.api.errors import ApiError
from app.api.schemas import ValuationRequestSchema
from app.api.v1.helpers import get_company_or_404, get_json_body
from app.extensions import db
from app.services import DcfAssumptions, ValuationError, run_scenarios, sensitivity_grid
from app.services.derivations import derive_dcf_inputs

bp = Blueprint("valuation", __name__)

DISCLAIMER = (
    "Illustrative DCF output for research/education only — not a price target or "
    "investment advice. 'capex_pct_revenue' is modelled net of depreciation."
)


def _round_grid(values: list[float], nd: int = 4) -> list[float]:
    return [round(v, nd) for v in values]


@bp.post("/<identifier>/valuation")
def run_valuation(identifier: str):
    company = get_company_or_404(identifier)
    body = ValuationRequestSchema().load(get_json_body())

    derived = derive_dcf_inputs(db.session, company.id, overrides=body["inputs"])
    assumptions = DcfAssumptions(**body["assumptions"])

    try:
        scenarios = run_scenarios(derived.inputs, assumptions)
    except ValuationError as exc:
        raise ApiError(str(exc), status=422, code="validation_error") from exc

    sensitivity = None
    if body["include_sensitivity"]:
        w = assumptions.wacc
        g = assumptions.terminal_growth
        wacc_values = _round_grid([w - 0.02, w - 0.01, w, w + 0.01, w + 0.02])
        tg_values = _round_grid([g - 0.01, g - 0.005, g, g + 0.005, g + 0.01])
        sensitivity = sensitivity_grid(derived.inputs, assumptions, wacc_values, tg_values)

    return jsonify({
        "company": {"id": company.id, "ticker": company.ticker, "name": company.name},
        "inputs": {
            **asdict(derived.inputs),
            "sources": derived.sources,          # per-input: sec | override | default
            "fiscal_year": derived.fiscal_year,
            "warnings": derived.warnings,
        },
        "assumptions": body["assumptions"],       # user-entered
        "scenarios": {name: asdict(res) for name, res in scenarios.items()},  # calculated
        "sensitivity": sensitivity,
        "disclaimer": DISCLAIMER,
    })
