"""Signal endpoints: run + persist, history, and a directional-agreement backtest stub."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

from flask import Blueprint, jsonify
from sqlalchemy import select

from app.api.schemas import SignalRequestSchema
from app.api.serializers import signal_run_to_dict
from app.api.v1.helpers import get_company_or_404, get_json_body
from app.extensions import db
from app.models import CatalystEvent, SignalRun
from app.services import SignalInputs, score_signal
from app.services.derivations import (
    estimate_cash_runway_quarters,
    next_catalyst_context,
    trailing_return_proxy,
)

bp = Blueprint("signals", __name__)

DISCLAIMER = (
    "Educational signal only — not investment advice and not a guaranteed return. "
    "Scores are a transparent weighted sum of the listed inputs."
)

_INPUT_KEYS = [
    "valuation_upside", "catalyst_outcome", "event_type",
    "days_to_next_catalyst", "abnormal_return", "cash_runway_quarters", "manual_confidence",
]


@bp.post("/companies/<identifier>/signals")
def run_signal(identifier: str):
    company = get_company_or_404(identifier)
    data = SignalRequestSchema().load(get_json_body())
    as_of = data["as_of_date"]

    kwargs = {k: data.get(k) for k in _INPUT_KEYS}
    derived_from = {}
    if data["auto_derive"]:
        ctx = next_catalyst_context(db.session, company.id, as_of=as_of)
        for k in ("catalyst_outcome", "event_type", "days_to_next_catalyst"):
            if kwargs[k] is None and ctx[k] is not None:
                kwargs[k] = ctx[k]
                derived_from[k] = "catalysts"
        if kwargs["cash_runway_quarters"] is None:
            runway = estimate_cash_runway_quarters(db.session, company.id)
            if runway is not None:
                kwargs["cash_runway_quarters"] = runway
                derived_from["cash_runway_quarters"] = "sec_metrics"
        if kwargs["abnormal_return"] is None:
            ar = trailing_return_proxy(db.session, company.id)
            if ar is not None:
                kwargs["abnormal_return"] = ar
                derived_from["abnormal_return"] = "market_prices (trailing-return proxy)"

    inputs = SignalInputs(**kwargs)
    result = score_signal(inputs)

    run = None
    if data["persist"]:
        run = SignalRun(
            company_id=company.id, signal=result.signal, score=result.score,
            confidence=result.confidence, as_of_date=as_of, engine_version=result.engine_version,
            inputs_snapshot=json.dumps(asdict(inputs)),
            rationale=json.dumps({
                "text": result.rationale,
                "components": result.components,
                "warnings": result.warnings,
            }),
        )
        db.session.add(run)
        db.session.commit()

    return jsonify({
        "company": {"id": company.id, "ticker": company.ticker},
        "signal": result.signal,
        "score": result.score,
        "confidence": result.confidence,
        "components": result.components,
        "rationale": result.rationale,
        "warnings": result.warnings,
        "inputs_used": asdict(inputs),
        "auto_derived": derived_from,
        "persisted_run_id": run.id if run else None,
        "disclaimer": DISCLAIMER,
    }), (201 if run else 200)


@bp.get("/companies/<identifier>/signals")
def list_signals(identifier: str):
    company = get_company_or_404(identifier)
    runs = db.session.execute(
        select(SignalRun).where(SignalRun.company_id == company.id).order_by(SignalRun.created_at.desc())
    ).scalars().all()
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "count": len(runs),
        "signal_runs": [signal_run_to_dict(r) for r in runs],
    })


@bp.get("/companies/<identifier>/signals/backtest")
def backtest(identifier: str):
    """Directional-agreement scaffold (look-ahead-safe).

    For each persisted signal we look ONLY at catalysts that resolved *after* the
    signal's as_of_date, then check whether the direction agreed with the outcome.
    Metrics are reported only when real evaluation data exists — we never fabricate
    an accuracy figure.
    """
    company = get_company_or_404(identifier)
    runs = db.session.execute(
        select(SignalRun).where(SignalRun.company_id == company.id)
    ).scalars().all()
    catalysts = db.session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company.id)
    ).scalars().all()

    evaluated = 0
    agreements = 0
    details = []
    for run in runs:
        anchor = run.as_of_date or (run.created_at.date() if run.created_at else date.today())
        # Only outcomes realized strictly after the signal was made (no look-ahead).
        future = [
            c for c in catalysts
            if c.outcome in {"positive", "negative"} and c.actual_date and c.actual_date > anchor
        ]
        if not future:
            continue
        future.sort(key=lambda c: c.actual_date)
        outcome = future[0].outcome
        agree = (run.signal == "long" and outcome == "positive") or (
            run.signal == "short" and outcome == "negative"
        )
        evaluated += 1
        agreements += int(agree)
        details.append({
            "signal_run_id": run.id, "signal": run.signal, "as_of_date": anchor.isoformat(),
            "next_resolved_outcome": outcome, "resolved_on": future[0].actual_date.isoformat(),
            "agreement": agree,
        })

    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "methodology": (
            "For each persisted signal, compare its direction (LONG/SHORT) against the "
            "first catalyst outcome that resolved AFTER the signal's as_of_date."
        ),
        "signals_total": len(runs),
        "evaluated": evaluated,
        "directional_agreement_rate": round(agreements / evaluated, 3) if evaluated else None,
        "note": (
            "No resolved post-signal catalysts yet — agreement rate is unavailable "
            "(no fabricated results)." if evaluated == 0 else
            "Small-sample scaffold; not a validated performance claim."
        ),
        "details": details,
    })
