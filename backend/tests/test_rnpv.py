"""Risk-adjusted NPV per drug and the sum-of-the-parts roll-up."""
from __future__ import annotations

import pytest

from app.services.rnpv import (
    Asset,
    Economics,
    aggregate,
    project_asset,
    revenue_path,
    sensitivity,
)
from app.services.rnpv_benchmarks import erosion_curve, probability_for, years_to_launch

ECONOMICS = Economics(gross_margin=0.8, commercial_cost_rate=0.2, tax_rate=0.21,
                      development_cost_per_year=100.0)
START = 2026


def marketed(**kwargs):
    base = {"name": "Trikafta", "kind": "marketed", "base_revenue": 1_000.0,
            "growth_rate": 0.0, "growth_years": 3, "loe_year": None}
    return Asset(**{**base, **kwargs})


def pipeline(**kwargs):
    base = {"name": "povetacicept", "kind": "pipeline", "peak_sales": 1_000.0,
            "launch_year": START + 2, "years_to_peak": 4, "probability": 0.524}
    return Asset(**{**base, **kwargs})


# --- Revenue curve -----------------------------------------------------------------
def test_marketed_growth_decays_then_holds():
    path = dict(revenue_path(marketed(growth_rate=0.10, growth_years=2), START, 6))
    assert path[START] == 1_000.0
    assert path[START + 1] == pytest.approx(1_100.0)      # full growth in the first step
    assert path[START + 2] == pytest.approx(1_155.0)      # decayed to half
    assert path[START + 3] == pytest.approx(1_155.0)      # growth exhausted, holds flat
    assert path[START + 4] == pytest.approx(1_155.0)


def test_pipeline_ramps_from_launch_to_peak_then_plateaus():
    path = dict(revenue_path(pipeline(launch_year=START + 2, years_to_peak=4), START, 10))
    assert path[START] == 0.0 and path[START + 1] == 0.0   # nothing before launch
    assert path[START + 2] == pytest.approx(250.0)         # first of four ramp years
    assert path[START + 5] == pytest.approx(1_000.0)       # peak reached
    assert path[START + 6] == pytest.approx(1_000.0)


def test_exclusivity_cliff_erodes_from_the_pre_loe_level():
    loe = START + 3
    path = dict(revenue_path(marketed(loe_year=loe, modality="small_molecule"), START, 12))
    retained = erosion_curve("small_molecule")
    assert path[loe - 1] == 1_000.0
    assert path[loe] == pytest.approx(1_000.0 * retained[0])
    assert path[loe + 1] == pytest.approx(1_000.0 * retained[1])
    # Beyond the curve the last step holds, never recovering.
    assert path[loe + 5] == pytest.approx(1_000.0 * retained[-1])


def test_biologics_erode_more_slowly_than_small_molecules():
    loe = START + 2
    small = dict(revenue_path(marketed(loe_year=loe, modality="small_molecule"), START, 6))
    biologic = dict(revenue_path(marketed(loe_year=loe, modality="biologic"), START, 6))
    assert biologic[loe] > small[loe]


# --- Cash flow and discounting ------------------------------------------------------
def test_marketed_year_one_arithmetic_and_discounting():
    result = project_asset(marketed(), ECONOMICS, 0.10, START, horizon=1)
    year = result.years[0]
    assert year["revenue"] == 1_000.0
    assert year["gross_profit"] == pytest.approx(800.0)        # 80% margin
    assert year["commercial_cost"] == pytest.approx(200.0)     # 20% of revenue
    assert year["development_cost"] == 0.0                     # marketed drugs do not develop
    assert year["pretax"] == pytest.approx(600.0)
    assert year["tax"] == pytest.approx(126.0)                 # 21% of positive pretax
    assert year["cash_flow"] == pytest.approx(474.0)
    assert year["discount_factor"] == pytest.approx(1 / 1.1)
    assert result.rnpv == pytest.approx(474.0 / 1.1)


def test_no_terminal_value_is_added_beyond_the_horizon():
    """A drug's value is the sum of its projected years and nothing more."""
    result = project_asset(marketed(), ECONOMICS, 0.10, START, horizon=5)
    assert result.rnpv == pytest.approx(sum(y["present_value"] for y in result.years))


def test_losses_are_not_taxed():
    result = project_asset(pipeline(launch_year=START + 5), ECONOMICS, 0.10, START, horizon=2)
    assert all(y["tax"] == 0.0 for y in result.years)
    assert all(y["pretax"] < 0 for y in result.years)          # development spending only


def test_probability_weights_revenue_but_not_development_spending():
    """Trials are paid for whether or not they succeed, so cost is not discounted by luck."""
    asset = pipeline(probability=0.5, launch_year=START + 1, years_to_peak=1)
    result = project_asset(asset, ECONOMICS, 0.0, START, horizon=2)
    development_year, selling_year = result.years
    # Year one is pure development: the full cost is borne.
    assert development_year["risked_cash_flow"] == pytest.approx(-100.0)
    # Year two is revenue: halved by the probability of ever getting there.
    assert selling_year["risked_cash_flow"] == pytest.approx(selling_year["cash_flow"] * 0.5)


def test_unvalued_assets_carry_their_reason_and_no_value():
    asset = pipeline(unvalued_reason="No patient population disclosed for this indication.")
    result = project_asset(asset, ECONOMICS, 0.10, START)
    assert result.rnpv is None and result.years == []
    assert "population" in result.unvalued_reason


# --- Aggregation --------------------------------------------------------------------
def build_results():
    return [project_asset(marketed(), ECONOMICS, 0.10, START, horizon=5),
            project_asset(pipeline(), ECONOMICS, 0.10, START, horizon=5)]


def test_waterfall_sums_to_equity_and_per_share():
    results = build_results()
    outcome = aggregate(results, overhead_per_year=50.0, net_cash=500.0,
                        shares_outstanding=100.0, discount_rate=0.10)
    assert outcome.asset_value == pytest.approx(sum(r.rnpv for r in results))
    assert outcome.equity_value == pytest.approx(
        outcome.asset_value - outcome.overhead_present_value + outcome.net_cash)
    assert outcome.value_per_share == pytest.approx(outcome.equity_value / 100.0)
    assert outcome.overhead_present_value > 0


def test_overhead_is_never_discounted_in_perpetuity():
    results = build_results()
    outcome = aggregate(results, 50.0, 0.0, 100.0, 0.10)
    perpetuity = 50.0 / 0.10
    assert outcome.overhead_present_value < perpetuity
    assert outcome.horizon_years == 5


def test_company_with_nothing_valuable_reports_no_value_rather_than_a_negative_one():
    """Research spending is attributed to programmes, so an unvalued pipeline cannot
    make a company worth less than its cash."""
    unvalued = project_asset(pipeline(unvalued_reason="No disclosed population."),
                             ECONOMICS, 0.10, START)
    outcome = aggregate([unvalued], overhead_per_year=400.0, net_cash=900.0,
                        shares_outstanding=100.0, discount_rate=0.10)
    assert outcome.equity_value is None and outcome.value_per_share is None
    assert outcome.asset_value is None
    assert "No drug could be valued" in outcome.note
    assert len(outcome.unvalued) == 1


def test_royalty_streams_carry_no_cost_of_goods_or_commercial_spend():
    royalty = Asset(name="Xtandi alliance", kind="royalty", base_revenue=1_000.0)
    year = project_asset(royalty, ECONOMICS, 0.10, START, horizon=1).years[0]
    assert year["gross_profit"] == pytest.approx(1_000.0)
    assert year["commercial_cost"] == 0.0


# --- Sensitivity --------------------------------------------------------------------
def test_sensitivity_reprojects_rather_than_scaling_a_finished_valuation():
    assets = [marketed(), pipeline()]
    grid = sensitivity(assets, ECONOMICS, 50.0, 500.0, 100.0, START,
                       discount_rates=[0.08, 0.10, 0.12], revenue_multipliers=[0.8, 1.0, 1.2],
                       horizon=5)
    values = grid["value_per_share"]
    assert len(values) == 3 and all(len(row) == 3 for row in values)
    # A higher discount rate lowers value; higher sales raise it.
    assert values[0][1] > values[2][1]
    assert values[1][0] < values[1][1] < values[1][2]
    # Costs do not scale with revenue, so the effect is not simply proportional.
    assert values[1][2] / values[1][1] != pytest.approx(1.2, abs=0.01)


# --- Benchmarks ---------------------------------------------------------------------
def test_benchmarks_are_conservative_where_evidence_is_thin():
    assert probability_for("phase_2_3") == probability_for("phase_2")   # the earlier phase
    assert probability_for("phase_3") > probability_for("phase_2")
    assert probability_for("filed") > probability_for("phase_3")
    # Preclinical has no published rate here and must not be invented.
    assert probability_for("preclinical") is None
    assert probability_for(None) is None
    assert years_to_launch("filed") < years_to_launch("phase_3") < years_to_launch("phase_1")


def test_expired_sales_are_not_eroded_twice():
    asset = marketed(base_revenue=100, loe_year=2023, base_revenue_year=2025)
    path = dict(revenue_path(asset, 2026, 3))
    assert path[2026] == pytest.approx(100 * .05 / .08)
    assert path[2027] == path[2026]


def test_mature_expired_sales_hold_reported_baseline():
    asset = marketed(base_revenue=100, loe_year=2020, base_revenue_year=2025)
    assert [v for _, v in revenue_path(asset, 2026, 3)] == [100, 100, 100]


def test_expiry_in_projection_still_applies_full_cliff():
    asset = marketed(base_revenue=100, loe_year=2026, base_revenue_year=2025)
    assert dict(revenue_path(asset, 2026, 2))[2026] == pytest.approx(35)
