"""Unit tests for the FMP analyst mapping (pure, no network)."""
from __future__ import annotations

from datetime import date

from app.providers.fmp_analyst import (
    _grade_action,
    _map_grade_row,
    _map_grades_consensus,
    _map_recommendation_row,
    consensus_label,
)


def test_map_grades_consensus():
    counts = _map_grades_consensus({
        "symbol": "PFE", "strongBuy": 0, "buy": 15, "hold": 23, "sell": 1,
        "strongSell": 0, "consensus": "Hold",
    })
    assert counts == {"strong_buy": 0, "buy": 15, "hold": 23, "sell": 1, "strong_sell": 0}


def test_map_grade_row_uses_explicit_action():
    rec = _map_grade_row({
        "gradingCompany": "Guggenheim", "previousGrade": "Buy",
        "newGrade": "Buy", "action": "maintain", "date": "2026-08-07",
    })
    assert rec is not None and rec.institution == "Guggenheim" and rec.action == "maintain"


def test_consensus_label_buckets():
    assert consensus_label(8, 2, 0, 0, 0) == "Strong Buy"
    assert consensus_label(0, 6, 3, 1, 0) == "Buy"
    assert consensus_label(0, 0, 10, 0, 0) == "Hold"
    assert consensus_label(0, 0, 3, 6, 1) == "Sell"
    assert consensus_label(0, 0, 0, 2, 8) == "Strong Sell"
    assert consensus_label(0, 0, 0, 0, 0) is None


def test_grade_action_classification():
    assert _grade_action("Hold", "Buy") == "upgrade"
    assert _grade_action("Buy", "Hold") == "downgrade"
    assert _grade_action(None, "Overweight") == "initiate"
    assert _grade_action("Buy", "Overweight") == "maintain"      # both bullish → no change
    assert _grade_action("Sell", "Underweight") == "maintain"    # both bearish


def test_map_recommendation_row():
    counts = _map_recommendation_row({
        "analystRatingsStrongBuy": 5, "analystRatingsbuy": 3, "analystRatingsHold": 2,
        "analystRatingsSell": 1, "analystRatingsStrongSell": 0,
    })
    assert counts == {"strong_buy": 5, "buy": 3, "hold": 2, "sell": 1, "strong_sell": 0}


def test_map_grade_row():
    rec = _map_grade_row({
        "gradingCompany": "Morgan Stanley", "previousGrade": "Hold",
        "newGrade": "Overweight", "date": "2026-08-01",
    })
    assert rec is not None
    assert rec.institution == "Morgan Stanley"
    assert rec.grade == "Overweight"
    assert rec.action == "upgrade"
    assert rec.rating_date == date(2026, 8, 1)


def test_map_grade_row_requires_institution():
    assert _map_grade_row({"newGrade": "Buy", "date": "2026-08-01"}) is None
