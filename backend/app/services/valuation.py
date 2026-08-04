"""Transparent discounted-cash-flow (DCF) valuation engine.

Simplified, auditable, and dependency-free so it is trivially testable.

Model (unlevered FCFF, Gordon terminal value)::

    revenue_t = revenue_{t-1} * (1 + growth_t)
    EBIT_t    = revenue_t * operating_margin
    NOPAT_t   = EBIT_t * (1 - tax_rate)
    ΔNWC_t    = nwc_pct_revenue * (revenue_t - revenue_{t-1})
    FCFF_t    = NOPAT_t - capex_t - ΔNWC_t          # capex is NET of D&A (see note)
    EV        = Σ FCFF_t / (1+wacc)^t  +  TV / (1+wacc)^N
    TV        = FCFF_N * (1 + g) / (wacc - g)
    Equity    = EV - net_debt
    Price     = Equity / shares_outstanding

Note on D&A: to match the requested input set (revenue growth, operating margin,
tax, capex, working capital, WACC, terminal growth, net debt, shares) we model
``capex_pct_revenue`` as *net* reinvestment (capital expenditure net of
depreciation). D&A therefore does not appear as a separate line. This is a
documented simplification, surfaced to the user, not a hidden assumption.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


class ValuationError(ValueError):
    """Raised when assumptions are internally inconsistent (e.g. WACC <= g)."""


@dataclass
class DcfAssumptions:
    """User-entered assumptions for one scenario. Rates are decimals (0.12 = 12%)."""

    revenue_growth: float          # constant annual growth applied each projection year
    operating_margin: float
    tax_rate: float
    capex_pct_revenue: float       # net capital investment as a % of revenue
    nwc_pct_revenue: float         # incremental working capital as a % of revenue change
    wacc: float
    terminal_growth: float
    projection_years: int = 5


@dataclass
class DcfInputs:
    """SEC-derived (or user-overridden) anchors for the model."""

    base_revenue: float            # last actual annual revenue (year 0)
    net_debt: float                # total debt - cash
    shares_outstanding: float


@dataclass
class YearProjection:
    year: int
    revenue: float
    ebit: float
    nopat: float
    capex: float
    delta_nwc: float
    fcff: float
    discount_factor: float
    pv_fcff: float


@dataclass
class DcfResult:
    scenario: str
    assumptions: dict
    projections: list[dict]
    pv_fcff_sum: float
    terminal_value: float
    pv_terminal_value: float
    enterprise_value: float
    equity_value: float
    implied_share_price: float
    warnings: list[str] = field(default_factory=list)


def _validate(inputs: DcfInputs, a: DcfAssumptions) -> None:
    if a.projection_years < 1:
        raise ValuationError("projection_years must be >= 1.")
    if a.wacc <= a.terminal_growth:
        raise ValuationError(
            f"WACC ({a.wacc:.2%}) must exceed terminal growth ({a.terminal_growth:.2%})."
        )
    if inputs.shares_outstanding <= 0:
        raise ValuationError("shares_outstanding must be positive.")
    if inputs.base_revenue <= 0:
        raise ValuationError("base_revenue must be positive.")


def run_dcf(inputs: DcfInputs, assumptions: DcfAssumptions, scenario: str = "base") -> DcfResult:
    """Run a single-scenario DCF and return the full, transparent breakdown."""
    _validate(inputs, assumptions)
    a = assumptions
    warnings: list[str] = []

    projections: list[YearProjection] = []
    prev_revenue = inputs.base_revenue
    pv_fcff_sum = 0.0
    last_fcff = 0.0

    for t in range(1, a.projection_years + 1):
        revenue = prev_revenue * (1 + a.revenue_growth)
        ebit = revenue * a.operating_margin
        nopat = ebit * (1 - a.tax_rate)
        capex = revenue * a.capex_pct_revenue
        delta_nwc = a.nwc_pct_revenue * (revenue - prev_revenue)
        fcff = nopat - capex - delta_nwc
        discount_factor = 1 / (1 + a.wacc) ** t
        pv_fcff = fcff * discount_factor

        projections.append(
            YearProjection(
                year=t, revenue=revenue, ebit=ebit, nopat=nopat, capex=capex,
                delta_nwc=delta_nwc, fcff=fcff, discount_factor=discount_factor, pv_fcff=pv_fcff,
            )
        )
        pv_fcff_sum += pv_fcff
        last_fcff = fcff
        prev_revenue = revenue

    # Gordon-growth terminal value on the final-year FCFF.
    terminal_value = last_fcff * (1 + a.terminal_growth) / (a.wacc - a.terminal_growth)
    pv_terminal_value = terminal_value / (1 + a.wacc) ** a.projection_years

    enterprise_value = pv_fcff_sum + pv_terminal_value
    equity_value = enterprise_value - inputs.net_debt
    implied_share_price = equity_value / inputs.shares_outstanding

    if last_fcff < 0:
        warnings.append(
            "Final-year FCFF is negative; the Gordon terminal value is unreliable here. "
            "Treat the implied price as illustrative."
        )
    if enterprise_value and pv_terminal_value / enterprise_value > 0.85:
        warnings.append("Terminal value exceeds 85% of enterprise value — result is TV-driven.")
    if implied_share_price < 0:
        warnings.append("Implied equity value is negative at these assumptions.")

    return DcfResult(
        scenario=scenario,
        assumptions=asdict(a),
        projections=[asdict(p) for p in projections],
        pv_fcff_sum=pv_fcff_sum,
        terminal_value=terminal_value,
        pv_terminal_value=pv_terminal_value,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        implied_share_price=implied_share_price,
        warnings=warnings,
    )


# --- Scenario helpers ------------------------------------------------------
@dataclass
class ScenarioDeltas:
    """Additive adjustments applied to the base case to build bull/bear cases."""

    revenue_growth: float = 0.0
    operating_margin: float = 0.0
    wacc: float = 0.0
    terminal_growth: float = 0.0


DEFAULT_BULL = ScenarioDeltas(revenue_growth=+0.04, operating_margin=+0.03, wacc=-0.01)
DEFAULT_BEAR = ScenarioDeltas(revenue_growth=-0.04, operating_margin=-0.03, wacc=+0.01)


def _apply_deltas(a: DcfAssumptions, d: ScenarioDeltas) -> DcfAssumptions:
    return DcfAssumptions(
        revenue_growth=max(-0.99, a.revenue_growth + d.revenue_growth),
        operating_margin=a.operating_margin + d.operating_margin,
        tax_rate=a.tax_rate,
        capex_pct_revenue=a.capex_pct_revenue,
        nwc_pct_revenue=a.nwc_pct_revenue,
        wacc=max(a.terminal_growth + d.terminal_growth + 0.005, a.wacc + d.wacc),
        terminal_growth=a.terminal_growth + d.terminal_growth,
        projection_years=a.projection_years,
    )


def run_scenarios(
    inputs: DcfInputs,
    base: DcfAssumptions,
    bull: ScenarioDeltas | None = None,
    bear: ScenarioDeltas | None = None,
) -> dict[str, DcfResult]:
    """Run base/bull/bear and return them keyed by scenario name."""
    bull = bull or DEFAULT_BULL
    bear = bear or DEFAULT_BEAR
    return {
        "base": run_dcf(inputs, base, "base"),
        "bull": run_dcf(inputs, _apply_deltas(base, bull), "bull"),
        "bear": run_dcf(inputs, _apply_deltas(base, bear), "bear"),
    }


def sensitivity_grid(
    inputs: DcfInputs,
    base: DcfAssumptions,
    wacc_values: list[float],
    terminal_growth_values: list[float],
) -> dict:
    """Implied-share-price grid over (WACC × terminal growth).

    Cells where the model is invalid (WACC <= g) are returned as ``None``.
    """
    rows = []
    for w in wacc_values:
        row = []
        for g in terminal_growth_values:
            try:
                a = DcfAssumptions(
                    revenue_growth=base.revenue_growth, operating_margin=base.operating_margin,
                    tax_rate=base.tax_rate, capex_pct_revenue=base.capex_pct_revenue,
                    nwc_pct_revenue=base.nwc_pct_revenue, wacc=w, terminal_growth=g,
                    projection_years=base.projection_years,
                )
                row.append(round(run_dcf(inputs, a).implied_share_price, 2))
            except ValuationError:
                row.append(None)
        rows.append(row)
    return {
        "wacc_values": wacc_values,
        "terminal_growth_values": terminal_growth_values,
        "implied_share_price": rows,
    }
