"""Tests for stage-aware biotech dashboard figures."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.biotech_profile import (
    HEADLINE,
    OPERATING_LOSS_BURN_CONFIDENCE,
    PRE_REVENUE_SPEND_RATIO,
    build_profile,
    classify_stage,
    runway_quarters,
)


def metric(value, status="reported", confidence=1.0, source="sec_edgar", unit="USD"):
    return SimpleNamespace(value=value, status=status, confidence=confidence, source=source,
                           unit=unit, quality_note=None)


def company(**values):
    return {concept: metric(value) for concept, value in values.items()}


# Shaped on Moderna FY2025: material revenue, negative cash flow, most funds in securities.
BURNING = company(
    revenue=1.94e9, operating_cash_flow=-1.87e9, free_cash_flow=-2.06e9, liquidity=8.13e9,
    cash=2.60e9, operating_income=-3.0e9, research_development=3.13e9, sga=1.02e9,
    shares_outstanding=394.9e6,
)
GENERATIVE = company(
    revenue=12.0e9, operating_cash_flow=3.63e9, free_cash_flow=3.19e9, liquidity=12.32e9,
    cash=5.08e9, operating_income=4.5e9, research_development=3.91e9, sga=1.75e9,
    shares_outstanding=254.0e6,
)
PRE_REVENUE = company(
    revenue=5e6, operating_cash_flow=-320e6, free_cash_flow=-330e6, liquidity=900e6,
    cash=150e6, operating_income=-360e6, research_development=280e6, sga=70e6,
    shares_outstanding=80e6,
)


def figure(profile, key):
    return profile["figures"][key]


# --- Stage classification ----------------------------------------------------
def test_classifies_each_stage_with_a_reason():
    stage, reason = classify_stage(PRE_REVENUE)
    assert stage == "pre_revenue"
    assert "10% threshold" in reason

    assert classify_stage(company(research_development=100e6, sga=20e6))[0] == "pre_revenue"
    stage, reason = classify_stage(BURNING)
    assert stage == "cash_burning" and "negative" in reason
    stage, reason = classify_stage(GENERATIVE)
    assert stage == "cash_generative" and "positive" in reason


def test_threshold_is_strictly_below_the_spend_ratio():
    spend = 1_000e6
    at_threshold = company(revenue=PRE_REVENUE_SPEND_RATIO * spend, operating_cash_flow=-1e6,
                           research_development=800e6, sga=200e6)
    assert classify_stage(at_threshold)[0] == "cash_burning"
    just_below = company(revenue=PRE_REVENUE_SPEND_RATIO * spend - 1, operating_cash_flow=-1e6,
                         research_development=800e6, sga=200e6)
    assert classify_stage(just_below)[0] == "pre_revenue"


def test_classification_falls_back_to_operating_income_and_says_so():
    profitable = company(revenue=5e9, operating_income=1e9, research_development=1e9, sga=1e9)
    stage, reason = classify_stage(profitable)
    assert stage == "cash_generative"
    assert "Operating cash flow is not reported" in reason

    unknown = company(revenue=5e9, research_development=1e9, sga=1e9)
    assert "could not be determined" in classify_stage(unknown)[1]


def test_missing_status_metrics_are_not_used():
    metrics = {**GENERATIVE, "operating_cash_flow": metric(3.63e9, status="missing")}
    assert "Operating cash flow is not reported" in classify_stage(metrics)[1]


# --- Runway --------------------------------------------------------------------
def test_runway_is_liquidity_over_operating_cash_burn():
    profile = build_profile(BURNING)
    runway = figure(profile, "runway_quarters")
    assert runway["value"] == pytest.approx(8.13e9 / (1.87e9 / 4))
    assert runway["unit"] == "quarters"
    assert set(runway["inputs"]) == {"liquidity", "operating_cash_flow"}
    assert figure(profile, "quarterly_burn")["value"] == pytest.approx(1.87e9 / 4)


def test_securities_heavy_company_no_longer_reads_as_financing_risk():
    """Regression: cash-only liquidity and operating-loss burn understated runway.

    The signal engine penalises runway below 4 quarters, so the old reading scored a
    company holding $8B as a financing risk.
    """
    old = BURNING["cash"].value / (-BURNING["operating_income"].value / 4)
    new = runway_quarters(BURNING)
    assert old < 4 <= new
    assert new == pytest.approx(17.39, abs=0.01)


def test_runway_not_meaningful_when_self_funding():
    runway = figure(build_profile(GENERATIVE), "runway_quarters")
    assert runway["value"] is None
    assert runway["status"] == "not_meaningful"
    assert runway_quarters(GENERATIVE) is None
    assert figure(build_profile(GENERATIVE), "quarterly_burn")["status"] == "not_meaningful"


def test_runway_falls_back_for_metrics_stored_before_cash_flow_was_normalized():
    legacy = company(revenue=1e9, cash=400e6, operating_income=-800e6,
                     research_development=600e6, sga=300e6)
    runway = figure(build_profile(legacy), "runway_quarters")
    assert runway["value"] == pytest.approx(400e6 / (800e6 / 4))
    assert runway["confidence"] == pytest.approx(OPERATING_LOSS_BURN_CONFIDENCE)
    assert "Cash only" in runway["note"]
    assert "operating loss" in runway["note"]


def test_runway_missing_without_any_cash_data():
    runway = figure(build_profile(company(revenue=1e9, operating_cash_flow=-4e8)), "runway_quarters")
    assert runway["value"] is None and runway["status"] == "missing"


# --- Ratios ---------------------------------------------------------------------
def test_ratio_arithmetic():
    profile = build_profile(GENERATIVE)
    assert figure(profile, "fcf_margin")["value"] == pytest.approx(3.19e9 / 12.0e9)
    assert figure(profile, "rd_intensity")["value"] == pytest.approx(3.91e9 / 12.0e9)
    assert figure(profile, "rd_share_of_spend")["value"] == pytest.approx(3.91e9 / (3.91e9 + 1.75e9))
    assert figure(profile, "fcf_margin")["unit"] == "ratio"


def test_revenue_ratios_are_withheld_for_pre_revenue_companies():
    profile = build_profile(PRE_REVENUE)
    for key in ("fcf_margin", "rd_intensity"):
        assert figure(profile, key)["value"] is None
        assert figure(profile, key)["status"] == "not_meaningful"
    # Share of spend does not depend on revenue, so it is still reported.
    assert figure(profile, "rd_share_of_spend")["value"] == pytest.approx(280 / 350)


def test_computed_confidence_is_the_weakest_input():
    metrics = {**GENERATIVE, "revenue": metric(12.0e9, confidence=0.7)}
    assert figure(build_profile(metrics), "fcf_margin")["confidence"] == pytest.approx(0.7)


def test_dilution_needs_a_prior_year():
    assert figure(build_profile(BURNING), "dilution_yoy")["value"] is None
    prior = company(shares_outstanding=385.6e6)
    dilution = figure(build_profile(BURNING, prior), "dilution_yoy")
    assert dilution["value"] == pytest.approx(394.9e6 / 385.6e6 - 1)


# --- Profile shape ---------------------------------------------------------------
@pytest.mark.parametrize("metrics, stage", [
    (PRE_REVENUE, "pre_revenue"), (BURNING, "cash_burning"), (GENERATIVE, "cash_generative"),
])
def test_headline_matches_stage_and_every_key_is_a_figure(metrics, stage):
    profile = build_profile(metrics, fiscal_year=2025)
    assert profile["stage"] == stage
    assert profile["headline"] == HEADLINE[stage]
    assert len(profile["headline"]) == 6
    assert set(profile["headline"]) <= set(profile["figures"])
    assert profile["fiscal_year"] == 2025
    assert profile["stage_label"] and profile["stage_reason"]


def test_pre_revenue_headline_drops_ebitda_style_figures():
    headline = build_profile(PRE_REVENUE)["headline"]
    assert "runway_quarters" in headline
    assert not {"revenue", "fcf_margin"} & set(headline)
