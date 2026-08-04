"""Tests for the DCF valuation engine."""
from __future__ import annotations

import math

import pytest

from app.services.valuation import (
    DcfAssumptions,
    DcfInputs,
    ValuationError,
    run_dcf,
    run_scenarios,
    sensitivity_grid,
)


@pytest.fixture()
def inputs():
    return DcfInputs(base_revenue=1_000.0, net_debt=200.0, shares_outstanding=100.0)


@pytest.fixture()
def base_assumptions():
    return DcfAssumptions(
        revenue_growth=0.10, operating_margin=0.20, tax_rate=0.21,
        capex_pct_revenue=0.05, nwc_pct_revenue=0.10, wacc=0.10, terminal_growth=0.02,
    )


def test_first_year_projection_math(inputs, base_assumptions):
    res = run_dcf(inputs, base_assumptions)
    y1 = res.projections[0]
    # revenue_1 = 1000 * 1.10
    assert y1["revenue"] == pytest.approx(1100.0)
    # ebit = 1100 * 0.20 ; nopat = ebit * 0.79
    assert y1["ebit"] == pytest.approx(220.0)
    assert y1["nopat"] == pytest.approx(220.0 * 0.79)
    # capex = 1100 * 0.05 ; dNWC = 0.10 * (1100 - 1000) = 10
    assert y1["capex"] == pytest.approx(55.0)
    assert y1["delta_nwc"] == pytest.approx(10.0)
    # fcff = nopat - capex - dNWC
    assert y1["fcff"] == pytest.approx(220.0 * 0.79 - 55.0 - 10.0)
    # discount factor = 1/1.1
    assert y1["discount_factor"] == pytest.approx(1 / 1.10)


def test_equity_bridge_and_share_price(inputs, base_assumptions):
    res = run_dcf(inputs, base_assumptions)
    assert res.equity_value == pytest.approx(res.enterprise_value - inputs.net_debt)
    assert res.implied_share_price == pytest.approx(res.equity_value / inputs.shares_outstanding)


def test_terminal_value_formula(inputs, base_assumptions):
    res = run_dcf(inputs, base_assumptions)
    last_fcff = res.projections[-1]["fcff"]
    expected_tv = last_fcff * (1 + base_assumptions.terminal_growth) / (
        base_assumptions.wacc - base_assumptions.terminal_growth
    )
    assert res.terminal_value == pytest.approx(expected_tv)
    expected_pv_tv = expected_tv / (1 + base_assumptions.wacc) ** base_assumptions.projection_years
    assert res.pv_terminal_value == pytest.approx(expected_pv_tv)


def test_enterprise_value_is_sum_of_pvs(inputs, base_assumptions):
    res = run_dcf(inputs, base_assumptions)
    assert res.enterprise_value == pytest.approx(res.pv_fcff_sum + res.pv_terminal_value)
    assert res.pv_fcff_sum == pytest.approx(sum(p["pv_fcff"] for p in res.projections))


def test_wacc_must_exceed_terminal_growth(inputs):
    bad = DcfAssumptions(
        revenue_growth=0.10, operating_margin=0.20, tax_rate=0.21,
        capex_pct_revenue=0.05, nwc_pct_revenue=0.10, wacc=0.03, terminal_growth=0.03,
    )
    with pytest.raises(ValuationError):
        run_dcf(inputs, bad)


def test_invalid_inputs_raise(base_assumptions):
    with pytest.raises(ValuationError):
        run_dcf(DcfInputs(base_revenue=0, net_debt=0, shares_outstanding=100), base_assumptions)
    with pytest.raises(ValuationError):
        run_dcf(DcfInputs(base_revenue=100, net_debt=0, shares_outstanding=0), base_assumptions)


def test_scenarios_ordering(inputs, base_assumptions):
    scenarios = run_scenarios(inputs, base_assumptions)
    assert set(scenarios) == {"base", "bull", "bear"}
    # Bull assumptions (higher growth/margin, lower WACC) should not undervalue vs bear.
    assert scenarios["bull"].implied_share_price > scenarios["bear"].implied_share_price
    assert scenarios["bear"].implied_share_price < scenarios["base"].implied_share_price < scenarios["bull"].implied_share_price


def test_higher_wacc_lowers_value(inputs, base_assumptions):
    low = run_dcf(inputs, base_assumptions).implied_share_price
    higher = DcfAssumptions(**{**base_assumptions.__dict__, "wacc": 0.14})
    assert run_dcf(inputs, higher).implied_share_price < low


def test_sensitivity_grid_shape_and_invalid_cells(inputs, base_assumptions):
    grid = sensitivity_grid(inputs, base_assumptions, [0.08, 0.10, 0.02], [0.02, 0.05])
    assert len(grid["implied_share_price"]) == 3
    assert all(len(row) == 2 for row in grid["implied_share_price"])
    # WACC row 0.02 with terminal growth 0.05 is invalid (wacc <= g) -> None cell present.
    assert any(cell is None for row in grid["implied_share_price"] for cell in row)


def test_all_numbers_finite(inputs, base_assumptions):
    res = run_dcf(inputs, base_assumptions)
    for field in (res.enterprise_value, res.equity_value, res.implied_share_price):
        assert math.isfinite(field)
