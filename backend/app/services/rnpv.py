"""Risk-adjusted NPV per drug, aggregated into a sum-of-the-parts company valuation.

Each drug is its own mini-company: a launch ramp to peak sales, a plateau, then the
exclusivity cliff and erosion. There is deliberately **no terminal value** — a drug's
economic life ends with its patents, and assuming perpetual growth is exactly what makes a
conventional DCF wrong for biotech.

Risk lives in the probability of reaching market, not in the discount rate, so the rate
must not also carry a clinical-risk premium or the same risk is charged twice.

Development spending is *not* probability-weighted: a company pays for trials whether or
not they succeed. That is the conservative treatment and keeps the model easy to explain.

Pure functions over plain dataclasses; callers supply values already read from filings.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.services.rnpv_benchmarks import (
    DEFAULT_COMMERCIAL_COST_RATE,
    DEFAULT_GROSS_MARGIN,
    HORIZON_YEARS,
    US_STATUTORY_TAX_RATE,
    erosion_curve,
)


@dataclass
class Economics:
    """Company-level cost structure, read from SEC filings where available."""

    gross_margin: float = DEFAULT_GROSS_MARGIN
    commercial_cost_rate: float = DEFAULT_COMMERCIAL_COST_RATE   # share of revenue
    tax_rate: float = US_STATUTORY_TAX_RATE
    development_cost_per_year: float = 0.0                        # per pipeline programme


@dataclass
class Asset:
    """One drug's model. Marketed drugs start from revenue; pipeline drugs from peak sales."""

    name: str
    kind: str                       # marketed | pipeline | royalty
    base_revenue: float = 0.0       # latest reported revenue (marketed, royalty)
    peak_sales: float | None = None  # pipeline
    launch_year: int | None = None
    years_to_peak: int = 5
    loe_year: int | None = None
    probability: float = 1.0
    growth_rate: float = 0.0
    growth_years: int = 3
    modality: str | None = None
    unvalued_reason: str | None = None
    base_revenue_year: int | None = None


@dataclass
class AssetYear:
    year: int
    revenue: float
    gross_profit: float
    commercial_cost: float
    development_cost: float
    pretax: float
    tax: float
    cash_flow: float
    risked_cash_flow: float
    discount_factor: float
    present_value: float


@dataclass
class AssetResult:
    name: str
    kind: str
    probability: float
    rnpv: float | None
    unrisked_npv: float | None
    peak_revenue: float | None
    loe_year: int | None
    years: list[dict] = field(default_factory=list)
    unvalued_reason: str | None = None


def revenue_path(asset: Asset, start_year: int, horizon: int) -> list[tuple[int, float]]:
    """Yearly revenue: ramp to peak, plateau to exclusivity loss, then erosion."""
    erosion = erosion_curve(asset.modality)
    path: list[tuple[int, float]] = []
    plateau = 0.0
    # Reported sales already include erosion through their fiscal year. Apply only
    # the remaining change in retention, never the full patent cliff a second time.
    baseline_year = asset.base_revenue_year
    if baseline_year is None:
        baseline_year = start_year if asset.loe_year is not None and asset.loe_year < start_year else start_year - 1
    def retention(year: int) -> float:
        index = year - asset.loe_year
        return 1.0 if index < 0 else erosion[min(index, len(erosion) - 1)]
    for offset in range(horizon):
        year = start_year + offset
        if asset.kind == "pipeline":
            launch = asset.launch_year if asset.launch_year is not None else start_year
            if year < launch:
                revenue = 0.0
            else:
                ramp = min(1.0, (year - launch + 1) / max(1, asset.years_to_peak))
                revenue = (asset.peak_sales or 0.0) * ramp
        else:
            # Growth decays linearly to zero across the growth years, then holds.
            years_in = offset
            if years_in == 0:
                revenue = asset.base_revenue
            else:
                previous = path[-1][1]
                decay = max(0.0, 1 - (years_in - 1) / max(1, asset.growth_years))
                revenue = previous * (1 + asset.growth_rate * decay)

        if asset.loe_year is not None and year >= asset.loe_year:
            if asset.kind != "pipeline" and asset.loe_year <= baseline_year:
                revenue = asset.base_revenue * retention(year) / retention(baseline_year)
                path.append((year, revenue))
                continue
            if plateau == 0.0:
                plateau = path[-1][1] if path else revenue
            index = year - asset.loe_year
            revenue = plateau * (erosion[index] if index < len(erosion) else erosion[-1])
        path.append((year, revenue))
    return path


def project_asset(asset: Asset, economics: Economics, discount_rate: float,
                  start_year: int, horizon: int = HORIZON_YEARS) -> AssetResult:
    """Yearly cash flows and the risk-adjusted present value of one drug."""
    if asset.unvalued_reason:
        return AssetResult(asset.name, asset.kind, asset.probability, None, None,
                           asset.peak_sales, asset.loe_year, [], asset.unvalued_reason)

    # Royalty and collaboration streams arrive net of the partner's costs.
    gross_margin = 1.0 if asset.kind == "royalty" else economics.gross_margin
    commercial_rate = 0.0 if asset.kind == "royalty" else economics.commercial_cost_rate

    years: list[AssetYear] = []
    present_value = 0.0
    unrisked = 0.0
    for offset, (year, revenue) in enumerate(revenue_path(asset, start_year, horizon), start=1):
        in_development = (asset.kind == "pipeline" and asset.launch_year is not None
                          and year < asset.launch_year)
        development = economics.development_cost_per_year if in_development else 0.0
        gross_profit = revenue * gross_margin
        commercial = revenue * commercial_rate
        pretax = gross_profit - commercial - development
        tax = max(0.0, pretax) * economics.tax_rate
        cash_flow = pretax - tax
        # Revenue is uncertain; the spending to get there is not.
        risked = (cash_flow + development) * asset.probability - development
        factor = 1 / (1 + discount_rate) ** offset
        years.append(AssetYear(year, revenue, gross_profit, commercial, development, pretax,
                               tax, cash_flow, risked, factor, risked * factor))
        present_value += risked * factor
        unrisked += cash_flow * factor

    peak = max((y.revenue for y in years), default=0.0)
    return AssetResult(asset.name, asset.kind, asset.probability, present_value, unrisked,
                       peak, asset.loe_year, [asdict(y) for y in years])


@dataclass
class Aggregate:
    """Sum-of-the-parts equity value, or an explicit refusal when nothing can be valued."""

    assets: list[dict]
    unvalued: list[dict]
    asset_value: float | None
    overhead_present_value: float
    net_cash: float
    equity_value: float | None
    value_per_share: float | None
    horizon_years: int
    note: str | None = None


def aggregate(results: list[AssetResult], overhead_per_year: float, net_cash: float,
              shares_outstanding: float | None, discount_rate: float) -> Aggregate:
    """Σ drug value − corporate overhead + net cash.

    Overhead is discounted only over the life of the drugs being valued, never in
    perpetuity. Research spending is not subtracted here: it belongs to each programme,
    and an unvalued programme's spending is excluded along with its value, so a company
    whose pipeline cannot be valued does not end up worth less than its cash.
    """
    valued = [r for r in results if r.rnpv is not None]
    unvalued = [r for r in results if r.rnpv is None]
    if not valued:
        return Aggregate([], [asdict(r) for r in unvalued], None, 0.0, net_cash, None, None, 0,
                         "No drug could be valued from the filing, so no company value is shown.")

    # Overhead runs until the last drug stops selling, counted from today rather than as a
    # tally of revenue years, so a programme launching in eight years extends it correctly.
    life = max((max((index for index, y in enumerate(r.years, start=1) if y["revenue"] > 0),
                    default=0) for r in valued), default=0)
    overhead_pv = sum(overhead_per_year / (1 + discount_rate) ** period
                      for period in range(1, life + 1))
    asset_value = sum(r.rnpv for r in valued)
    equity = asset_value - overhead_pv + net_cash
    per_share = equity / shares_outstanding if shares_outstanding else None
    return Aggregate([asdict(r) for r in valued], [asdict(r) for r in unvalued], asset_value,
                     overhead_pv, net_cash, equity, per_share, life)


def sensitivity(assets: list[Asset], economics: Economics, overhead_per_year: float,
                net_cash: float, shares_outstanding: float | None, start_year: int,
                discount_rates: list[float], revenue_multipliers: list[float],
                horizon: int = HORIZON_YEARS) -> dict:
    """Value per share across discount rates and a proportional shift in every drug's sales.

    Each cell re-projects the drugs: costs do not scale with revenue, so scaling a finished
    valuation would misstate the effect.
    """
    grid = []
    for rate in discount_rates:
        row = []
        for multiplier in revenue_multipliers:
            scaled = [replace_revenue(asset, multiplier) for asset in assets]
            results = [project_asset(a, economics, rate, start_year, horizon) for a in scaled]
            outcome = aggregate(results, overhead_per_year, net_cash, shares_outstanding, rate)
            row.append(None if outcome.value_per_share is None else round(outcome.value_per_share, 2))
        grid.append(row)
    return {"discount_rates": discount_rates, "revenue_multipliers": revenue_multipliers,
            "value_per_share": grid}


def replace_revenue(asset: Asset, multiplier: float) -> Asset:
    """A copy of the drug with its sales scaled, leaving costs and timing untouched."""
    scaled = Asset(**asdict(asset))
    scaled.base_revenue = asset.base_revenue * multiplier
    scaled.peak_sales = None if asset.peak_sales is None else asset.peak_sales * multiplier
    return scaled
