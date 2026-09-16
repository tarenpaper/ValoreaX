"""Signal endpoints: run + persist, history, and a directional-agreement backtest stub."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

from flask import Blueprint, current_app, jsonify
from sqlalchemy import select

from app.api.schemas import SignalRequestSchema
from app.api.serializers import signal_run_to_dict
from app.api.v1.helpers import cache_service, get_company_or_404, get_json_body
from app.extensions import db
from app.models import SignalRun
from app.services import SignalInputs, score_signal
from app.services.derivations import (
    derive_analyst_signal_inputs,
    derive_financial_health_inputs,
    derive_news_signal_inputs,
    derive_structural_signal_inputs,
    derive_valuation_signal_inputs,
    latest_catalyst_abnormal_return,
    next_catalyst_context,
    trailing_benchmark_adjusted_return,
)
from app.services.evaluation import METHODOLOGY, evaluate_company

bp = Blueprint("signals", __name__)

DISCLAIMER = (
    "Educational signal only — not investment advice and not a guaranteed return. "
    "Scores are a transparent weighted sum of the listed inputs."
)

_INPUT_KEYS = [
    "valuation_upside", "catalyst_outcome", "event_type", "days_to_next_catalyst",
    "abnormal_return", "cash_runway_quarters", "fcf_margin", "dilution_yoy",
    "analyst_consensus", "manual_confidence",
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
        # Analyst coverage drives its own component and nothing else. It used to also
        # auto-fill valuation_upside, which let one opinion reach the score twice.
        analyst = derive_analyst_signal_inputs(db.session, company.id)
        if kwargs["analyst_consensus"] is None and analyst.get("analyst_consensus") is not None:
            kwargs["analyst_consensus"] = analyst["analyst_consensus"]
            derived_from["analyst_consensus"] = "analyst_coverage"
        if analyst.get("analyst_label"):
            kwargs["analyst_label"] = analyst["analyst_label"]

        # Valuation: the drug model's multiple against the premium its peers carry.
        if kwargs["valuation_upside"] is None:
            valuation = derive_valuation_signal_inputs(
                db.session, company, cache_service(),
                benchmark_symbol=current_app.config["MARKET_BENCHMARK_TICKER"])
            if valuation:
                kwargs.update(valuation)
                derived_from["valuation"] = (
                    f"sum_of_the_parts ({valuation['valuation_basis']}: "
                    f"{valuation['valuation_basis_detail']})")

        # Patent-cliff exposure and concentration come from the same valuation.
        structural = derive_structural_signal_inputs(db.session, company)
        if structural:
            kwargs.update(structural)
            derived_from["exclusivity_runway"] = "drug_valuation"

        for key, value in derive_financial_health_inputs(db.session, company.id).items():
            if kwargs.get(key) is None:
                kwargs[key] = value
                derived_from[key] = "sec_metrics"

        news = derive_news_signal_inputs(db.session, company.id, as_of=calculation_as_of)
        if news:
            kwargs.update(news)
            derived_from["news_sentiment"] = "news_articles (high impact only)"

        context = next_catalyst_context(db.session, company.id, as_of=calculation_as_of)
        for key in ("catalyst_outcome", "event_type", "days_to_next_catalyst"):
            if kwargs[key] is None and context[key] is not None:
                kwargs[key] = context[key]
                derived_from[key] = "catalysts"
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
                "skipped": result.skipped,
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
        "skipped": result.skipped,
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
    stats = evaluate_company(db.session, company.id)
    agreement_rate = stats.pop("directional_agreement_rate")
    stats.pop("agreements", None)
    return jsonify({
        "company_id": company.id,
        "ticker": company.ticker,
        "methodology": METHODOLOGY,
        "directional_agreement_rate": agreement_rate,
        **stats,
    })
