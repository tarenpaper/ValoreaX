"""Seed a clearly-labelled example company with fictional sample assumptions.

Run:
    python -m app.seed            # seed (idempotent-ish; refreshes the example)
    python -m app.seed --if-empty # only seed when the DB has no companies

Everything created here is illustrative SAMPLE data (the company name carries a
"(SAMPLE)" tag, catalysts note they are illustrative, and market prices are
synthetic). Nothing is presented as real reported or market data.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import CatalystEvent, Company, SignalRun
from app.providers import get_market_provider
from app.services import CacheService, SignalInputs, ingest_company, score_signal

EXAMPLE_TICKER = "VALX"
EXAMPLE_BENCHMARK = "XLV"


def _seed_prices(company: Company) -> tuple[int, int]:
    """Seed deterministic synthetic issuer and benchmark prices for the example."""
    provider = get_market_provider()
    from app.models import BenchmarkPrice, MarketPrice

    db.session.execute(MarketPrice.__table__.delete().where(MarketPrice.company_id == company.id))
    db.session.execute(BenchmarkPrice.__table__.delete().where(BenchmarkPrice.symbol == EXAMPLE_BENCHMARK))

    company_points = provider.get_prices(company.ticker)
    benchmark_points = provider.get_prices(EXAMPLE_BENCHMARK)
    for point in company_points:
        db.session.add(MarketPrice(
            company_id=company.id,
            date=point.date,
            close=point.close,
            volume=point.volume,
            source=provider.name,
        ))
    for point in benchmark_points:
        db.session.add(BenchmarkPrice(
            symbol=EXAMPLE_BENCHMARK,
            date=point.date,
            close=point.close,
            volume=point.volume,
            source=provider.name,
        ))
    db.session.commit()
    return len(company_points), len(benchmark_points)


def _seed_catalysts(company: Company) -> None:
    if company.catalysts:
        return
    today = date.today()
    samples = [
        CatalystEvent(
            company_id=company.id, drug_program="VLX-310", indication="Metastatic solid tumors",
            event_type="phase_readout", trial_phase="Phase 2",
            expected_date=today - timedelta(days=90), actual_date=today - timedelta(days=85),
            outcome="positive", source="manual",
            notes="Illustrative SAMPLE catalyst — not a real clinical event.",
        ),
        CatalystEvent(
            company_id=company.id, drug_program="VLX-201", indication="Rare autoimmune disease",
            event_type="pdufa", trial_phase="Filed",
            expected_date=today + timedelta(days=48), actual_date=None, outcome="pending",
            source="manual",
            notes="Illustrative SAMPLE catalyst — upcoming FDA decision (not real).",
        ),
    ]
    db.session.add_all(samples)
    db.session.commit()


def _seed_signals(company: Company) -> None:
    if company.signal_runs:
        return
    today = date.today()

    from app.services.derivations import (
        estimate_cash_runway_quarters,
        next_catalyst_context,
        trailing_benchmark_adjusted_return,
    )
    context = next_catalyst_context(db.session, company.id)
    market_result = trailing_benchmark_adjusted_return(
        db.session, company.id, EXAMPLE_BENCHMARK, lookback_trading_days=20
    )
    current = SignalInputs(
        valuation_upside=0.28,
        catalyst_outcome=context["catalyst_outcome"], event_type=context["event_type"],
        days_to_next_catalyst=context["days_to_next_catalyst"],
        abnormal_return=market_result["abnormal_return"] if market_result else None,
        cash_runway_quarters=estimate_cash_runway_quarters(db.session, company.id),
        manual_confidence=0.7,
    )
    current_result = score_signal(current)
    db.session.add(SignalRun(
        company_id=company.id, signal=current_result.signal, score=current_result.score,
        confidence=current_result.confidence, as_of_date=today,
        engine_version=current_result.engine_version, inputs_snapshot=json.dumps(asdict(current)),
        rationale=json.dumps({
            "text": current_result.rationale,
            "components": current_result.components,
            "warnings": current_result.warnings,
        }),
    ))

    # A HISTORICAL sample signal dated before the resolved catalyst, so the
    # look-ahead-safe backtest scaffold has one sample datapoint to score.
    historical_inputs = SignalInputs(
        valuation_upside=0.40, catalyst_outcome="pending", event_type="phase_readout",
        abnormal_return=0.12, cash_runway_quarters=9.0, manual_confidence=0.85,
    )
    historical_result = score_signal(historical_inputs)
    db.session.add(SignalRun(
        company_id=company.id, signal=historical_result.signal, score=historical_result.score,
        confidence=historical_result.confidence, as_of_date=today - timedelta(days=150),
        engine_version=historical_result.engine_version,
        inputs_snapshot=json.dumps(asdict(historical_inputs)),
        rationale=json.dumps({
            "text": historical_result.rationale,
            "components": historical_result.components,
            "warnings": historical_result.warnings,
        }),
    ))
    db.session.commit()


def seed(if_empty: bool = False) -> None:
    app = create_app()
    with app.app_context():
        existing = db.session.execute(select(Company)).scalars().first()
        if if_empty and existing is not None:
            print("Database already has companies; skipping seed (--if-empty).")
            return

        # Seed exclusively from deterministic local sample providers. This avoids
        # API calls/credits even when a live provider is configured in .env.
        app.config["SEC_PROVIDER"] = "mock"
        app.config["MARKET_DATA_PROVIDER"] = "mock"
        result = ingest_company(
            db.session,
            EXAMPLE_TICKER,
            CacheService(db.session),
            app.config,
            is_example=True,
        )
        company = result.company
        print(
            f"Seeded example company {company.ticker} ({company.name}): "
            f"{result.metric_count} metrics, {result.filing_count} filings."
        )

        issuer_prices, benchmark_prices = _seed_prices(company)
        _seed_catalysts(company)
        _seed_signals(company)
        print(
            f"Added {issuer_prices} synthetic issuer prices and {benchmark_prices} "
            "synthetic benchmark prices, sample catalysts, and signal runs."
        )
        print("Done. NOTE: all seeded data is illustrative SAMPLE data, not real.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the ValoreaX example company.")
    parser.add_argument("--if-empty", action="store_true", help="Only seed when no companies exist yet.")
    args = parser.parse_args()
    seed(if_empty=args.if_empty)


if __name__ == "__main__":
    main()
