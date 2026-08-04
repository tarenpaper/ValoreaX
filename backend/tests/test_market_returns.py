"""Tests for benchmark-aligned market-return calculations."""
from __future__ import annotations

from datetime import date

from app.models import BenchmarkPrice, Company, MarketPrice
from app.services.derivations import (
    event_window_abnormal_return,
    trailing_benchmark_adjusted_return,
)


def _seed_prices(db):
    company = Company(ticker="TEST", name="Test Therapeutics", source="manual")
    db.session.add(company)
    db.session.flush()
    observations = [
        (date(2026, 1, 2), 100.0, 100.0),  # close before the event
        (date(2026, 1, 5), 110.0, 101.0),  # event session
        (date(2026, 1, 6), 112.0, 102.0),
        (date(2026, 1, 7), 115.0, 103.0),
        (date(2026, 1, 8), 118.0, 104.0),
        (date(2026, 1, 9), 120.0, 105.0),
        (date(2026, 1, 12), 125.0, 106.0),  # fifth session after the event
    ]
    for observed_on, company_close, benchmark_close in observations:
        db.session.add(MarketPrice(
            company_id=company.id,
            date=observed_on,
            close=company_close,
            source="test",
        ))
        db.session.add(BenchmarkPrice(
            symbol="XLV",
            date=observed_on,
            close=benchmark_close,
            source="test",
        ))
    db.session.commit()
    return company


def test_event_window_uses_aligned_closes_and_subtracts_benchmark(db):
    company = _seed_prices(db)
    result = event_window_abnormal_return(
        db.session,
        company.id,
        "XLV",
        date(2026, 1, 5),
        window_trading_days=5,
    )

    assert result is not None
    assert result["start_date"] == "2026-01-02"
    assert result["end_date"] == "2026-01-12"
    assert result["company_return"] == 0.25
    assert result["benchmark_return"] == 0.06
    assert result["abnormal_return"] == 0.19
    assert result["benchmark"] == "XLV"


def test_event_window_requires_complete_post_event_window(db):
    company = _seed_prices(db)
    result = event_window_abnormal_return(
        db.session,
        company.id,
        "XLV",
        date(2026, 1, 12),
        window_trading_days=5,
    )
    assert result is None


def test_trailing_return_is_benchmark_adjusted(db):
    company = _seed_prices(db)
    result = trailing_benchmark_adjusted_return(
        db.session,
        company.id,
        "XLV",
        lookback_trading_days=5,
    )

    assert result is not None
    assert result["company_return"] == 0.136364
    assert result["benchmark_return"] == 0.049505
    assert result["abnormal_return"] == 0.086859
