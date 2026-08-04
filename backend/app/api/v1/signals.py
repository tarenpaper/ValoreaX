"""Signal endpoints: run + persist, history, and a directional-agreement backtest stub."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

from flask import Blueprint, current_app, jsonify
from sqlalchemy import select

from app.api.schemas import SignalRequestSchema
from app.api.serializers import signal_run_to_dict
from app.api.v1.helpers import get_company_or_404, get_json_body
from app.extensions import db
from app.models import CatalystEvent, SignalRun
from app.services import SignalInputs, score_signal
from app.services.derivations import (
    estimate_cash_runway_quarters,
    latest_catalyst_abnormal_return,
    next_catalyst_context,
    trailing_benchmark_adjusted_return,
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
    calculation_as_of = as_of or date.today()

    kwargs = {key: data.get(key) for key in _INPUT_KEYS}
    derived_from = {}
    if data["auto_derive"]:
        context = next_catalyst_context(db.session, company.id, as_of=calculation_as_of)
        for key in ("catalyst_outcome", "event_type", "days_to_next_catalyst"):
            if kwargs[key] is None and context[key] is not None:
                kwargs[key] = context[key]
                derived_from[key] = "catalysts"
        if kwargs["cash_runway_quarters"] is None:
            runway = estimate_cash_runway_quarters(db.session, company.id)
            if runway is not None:
                kwargs["cash_runway_quarters"] = runway
                derived_from["cash_runway_quarters"] = "sec_metrics"
        if kwargs["abnormal_return"] is None:
            benchmark = current_app.config["MARKET_BENCHMARK_TICKER"]
            event_window = current_app.config["MARKET_EVENT_WINDOW_TRADING_DAYS"]
            market_result = latest_catalyst_abnormal_return(
                db.session,
                company.id,
                benchmark,
                calculation_as_of,
                window_trading_days=event_window,
            )
            if market_result is None:
                market_result = trailing_benchmark_adjusted_return(
                    db.session, company.id, benchmark, lookback_trading_days=20
                )
            if market_result is not None:
                kwargs["abnormal_return"] = market_result["abnormal_return"]
                derived_from["abnormal_return"] = (
                    f"market_prices ({market_result['methodology']}; "
                    f"benchmark={market_result['benchmark']}; "
                    f"{market_result['start_date']} to {market_result['end_date']})"
                )

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
        "signal_runs": [signal_run_to_dict(run) for run in runs],
    })


@bp.get("/companies/<identifier>/signals/backtest")
def backtest(identifier: str):
    """Directional-agreement scaffold (look-ahead-safe)."""
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
        future = [
            catalyst for catalyst in catalysts
            if catalyst.outcome in {"positive", "negative"}
            and catalyst.actual_date
            and catalyst.actual_date > anchor
        ]
        if not future:
            continue
        future.sort(key=lambda catalyst: catalyst.actual_date)
        outcome = future[0].outcome
        agree = (run.signal == "long" and outcome == "positive") or (
            run.signal == "short" and outcome == "negative"
        )
        evaluated += 1
        agreements += int(agree)
        details.append({
            "signal_run_id": run.id,
            "signal": run.signal,
            "as_of_date": anchor.isoformat(),
            "next_resolved_outcome": outcome,
            "resolved_on": future[0].actual_date.isoformat(),
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
