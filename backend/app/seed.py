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


def _seed_prices(company: Company, benchmark_symbol: str) -> int:
    provider = get_market_provider()
    from app.models import BenchmarkPrice, MarketPrice
    db.session.execute(MarketPrice.__table__.delete().where(MarketPrice.company_id == company.id))
    db.session.execute(
        BenchmarkPrice.__table__.delete().where(BenchmarkPrice.symbol == benchmark_symbol)
    )
    points = provider.get_prices(company.ticker)
    for p in points:
        db.session.add(MarketPrice(company_id=company.id, date=p.date, close=p.close,
                                   volume=p.volume, source=provider.name))
    # Seed the benchmark series too, so benchmark-adjusted (abnormal) returns are computable.
    for p in provider.get_prices(benchmark_symbol):
        db.session.add(BenchmarkPrice(symbol=benchmark_symbol, date=p.date, close=p.close,
                                      volume=p.volume, source=provider.name))
    db.session.commit()
    return len(points)


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


def _seed_signals(company: Company, benchmark_symbol: str) -> None:
    if company.signal_runs:
        return
    today = date.today()

    # A current signal (auto-derived from the seeded sample data).
    from app.services.derivations import (
        estimate_cash_runway_quarters,
        next_catalyst_context,
        trailing_benchmark_adjusted_return,
    )
    ctx = next_catalyst_context(db.session, company.id)
    market = trailing_benchmark_adjusted_return(db.session, company.id, benchmark_symbol)
    current = SignalInputs(
        valuation_upside=0.28,
        catalyst_outcome=ctx["catalyst_outcome"], event_type=ctx["event_type"],
        days_to_next_catalyst=ctx["days_to_next_catalyst"],
        abnormal_return=market["abnormal_return"] if market else None,
        cash_runway_quarters=estimate_cash_runway_quarters(db.session, company.id),
        manual_confidence=0.7,
    )
    r_current = score_signal(current)
    db.session.add(SignalRun(
        company_id=company.id, signal=r_current.signal, score=r_current.score,
        confidence=r_current.confidence, as_of_date=today, engine_version=r_current.engine_version,
        inputs_snapshot=json.dumps(asdict(current)),
        rationale=json.dumps({"text": r_current.rationale, "components": r_current.components,
                              "warnings": r_current.warnings}),
    ))

    # A HISTORICAL sample signal dated before the resolved catalyst, so the
    # look-ahead-safe backtest scaffold has one real (sample) datapoint to score.
    # It uses ONLY pre-event information (no knowledge of the outcome that later
    # resolves) — the whole point of guarding against look-ahead bias.
    historical_inputs = SignalInputs(
        valuation_upside=0.40, catalyst_outcome="pending", event_type="phase_readout",
        abnormal_return=0.12, cash_runway_quarters=9.0, manual_confidence=0.85,
    )
    r_hist = score_signal(historical_inputs)
    db.session.add(SignalRun(
        company_id=company.id, signal=r_hist.signal, score=r_hist.score,
        confidence=r_hist.confidence, as_of_date=today - timedelta(days=150),
        engine_version=r_hist.engine_version, inputs_snapshot=json.dumps(asdict(historical_inputs)),
        rationale=json.dumps({"text": r_hist.rationale, "components": r_hist.components,
                              "warnings": r_hist.warnings}),
    ))
    db.session.commit()


def seed(if_empty: bool = False) -> None:
    app = create_app()
    with app.app_context():
        existing = db.session.execute(select(Company)).scalars().first()
        if if_empty and existing is not None:
            print("Database already has companies; skipping seed (--if-empty).")
            return

        # Seed the example deterministically from the mock provider.
        app.config["SEC_PROVIDER"] = "mock"
        result = ingest_company(db.session, EXAMPLE_TICKER, CacheService(db.session),
                                app.config, is_example=True)
        company = result.company
        print(f"Seeded example company {company.ticker} ({company.name}): "
              f"{result.metric_count} metrics, {result.filing_count} filings.")

        benchmark_symbol = app.config.get("MARKET_BENCHMARK_TICKER", "XLV")
        n_prices = _seed_prices(company, benchmark_symbol)
        _seed_catalysts(company)
        _seed_signals(company, benchmark_symbol)
        print(f"Added {n_prices} synthetic prices, sample catalysts, and signal runs.")
        print("Done. NOTE: all seeded data is illustrative SAMPLE data, not real.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the ValoreaX example company.")
    parser.add_argument("--if-empty", action="store_true",
                        help="Only seed when no companies exist yet.")
    args = parser.parse_args()
    seed(if_empty=args.if_empty)


if __name__ == "__main__":
    main()
