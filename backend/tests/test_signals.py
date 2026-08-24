"""Tests for the transparent signal engine."""
from __future__ import annotations

from app.services.signals import (
    CONFIDENCE_FLOOR,
    LONG_THRESHOLD,
    SHORT_THRESHOLD,
    W_ANALYST,
    SignalInputs,
    score_signal,
)


def test_strong_bullish_inputs_yield_long():
    res = score_signal(SignalInputs(
        valuation_upside=0.40, catalyst_outcome="positive", event_type="pdufa",
        days_to_next_catalyst=20, abnormal_return=0.10, cash_runway_quarters=10,
        manual_confidence=0.9,
    ))
    assert res.signal == "long"
    assert res.score >= LONG_THRESHOLD
    assert 0 <= res.confidence <= 1


def test_strong_bearish_inputs_yield_short():
    res = score_signal(SignalInputs(
        valuation_upside=-0.40, catalyst_outcome="negative", event_type="crl",
        abnormal_return=-0.15, cash_runway_quarters=1.0, manual_confidence=0.9,
    ))
    assert res.signal == "short"
    assert res.score <= SHORT_THRESHOLD


def test_neutral_inputs_yield_watchlist():
    res = score_signal(SignalInputs(
        valuation_upside=0.02, catalyst_outcome="pending", event_type="pdufa",
        abnormal_return=0.0, cash_runway_quarters=6, manual_confidence=0.9,
    ))
    assert res.signal == "watchlist"


def test_low_confidence_forces_watchlist_even_with_high_score():
    # Only one input present and no manual confidence -> confidence below floor.
    res = score_signal(SignalInputs(valuation_upside=0.5))
    assert res.confidence < CONFIDENCE_FLOOR
    assert res.signal == "watchlist"
    assert "floor" in res.rationale.lower()


def test_high_impact_event_amplifies_catalyst_contribution():
    # Use a non-saturating outcome ('mixed', factor -0.3) so the ×1.2 high-impact
    # multiplier is visible; a fully 'positive' outcome already hits the cap.
    high = score_signal(SignalInputs(catalyst_outcome="mixed", event_type="pdufa",
                                     valuation_upside=0.0, manual_confidence=1.0))
    low = score_signal(SignalInputs(catalyst_outcome="mixed", event_type="other",
                                    valuation_upside=0.0, manual_confidence=1.0))
    high_c = next(c for c in high.components if c["name"] == "catalyst_outcome")
    low_c = next(c for c in low.components if c["name"] == "catalyst_outcome")
    assert abs(high_c["contribution"]) > abs(low_c["contribution"])


def test_positive_outcome_saturates_component_cap():
    res = score_signal(SignalInputs(catalyst_outcome="positive", event_type="pdufa",
                                    valuation_upside=0.0, manual_confidence=1.0))
    catalyst = next(c for c in res.components if c["name"] == "catalyst_outcome")
    assert catalyst["contribution"] == catalyst["weight"]  # capped, never exceeds weight


def test_contributions_sum_to_score():
    res = score_signal(SignalInputs(
        valuation_upside=0.2, catalyst_outcome="mixed", event_type="adcomm",
        abnormal_return=0.05, cash_runway_quarters=2, manual_confidence=0.6,
    ))
    total = round(sum(c["contribution"] for c in res.components), 2)
    assert total == res.score


def test_rationale_lists_every_component():
    inputs = SignalInputs(valuation_upside=0.2, catalyst_outcome="positive",
                          abnormal_return=0.05, cash_runway_quarters=5, manual_confidence=0.8)
    res = score_signal(inputs)
    # One explanation line per component plus a final decision line.
    assert len(res.rationale.splitlines()) == len(res.components) + 1


def test_more_inputs_increase_confidence():
    few = score_signal(SignalInputs(valuation_upside=0.2, manual_confidence=1.0))
    many = score_signal(SignalInputs(
        valuation_upside=0.2, catalyst_outcome="positive",
        abnormal_return=0.05, cash_runway_quarters=6, manual_confidence=1.0,
    ))
    assert many.confidence > few.confidence


def test_missing_inputs_are_simply_skipped():
    res = score_signal(SignalInputs(valuation_upside=0.3, manual_confidence=1.0))
    names = {c["name"] for c in res.components}
    assert names == {"valuation_upside"}


def test_analyst_consensus_bullish_contributes_positively():
    res = score_signal(SignalInputs(analyst_consensus=1.0, analyst_label="Strong Buy",
                                    manual_confidence=1.0))
    comp = next(c for c in res.components if c["name"] == "analyst_consensus")
    assert comp["contribution"] == W_ANALYST          # +1 tilt saturates the weight
    assert "Strong Buy" in comp["explanation"]


def test_analyst_consensus_bearish_is_negative():
    res = score_signal(SignalInputs(analyst_consensus=-0.8, manual_confidence=1.0))
    comp = next(c for c in res.components if c["name"] == "analyst_consensus")
    assert comp["contribution"] < 0


def test_component_weights_sum_to_100():
    from app.services.signals import (
        W_ABNORMAL_RETURN,
        W_ANALYST,
        W_CASH_RUNWAY,
        W_CATALYST,
        W_VALUATION,
    )
    assert W_VALUATION + W_CATALYST + W_ANALYST + W_ABNORMAL_RETURN + W_CASH_RUNWAY == 100.0
