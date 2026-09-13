"""Biotech-tailored dashboard figures derived from normalized SEC metrics.

Generic headline figures (EBITDA, operating income) mislead for biotech. Most companies
are pre-revenue, so margins are undefined, while runway, burn, dilution and R&D
reinvestment drive the equity story. This module turns stored annual metrics into those
figures and classifies each company by its economics, so the dashboard leads with the
figures that are meaningful for it.

Every figure is a pure function of stored, provenance-carrying metrics and names the
concepts it was computed from. Nothing is estimated from outside data or fetched.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Revenue below this share of R&D + SG&A spend counts as pre-revenue. A transparent,
# adjustable judgement call, not an industry standard.
PRE_REVENUE_SPEND_RATIO = 0.10

# Burn estimated from operating loss (which includes non-cash costs) is less reliable
# than burn from operating cash flow, so its confidence is scaled down.
OPERATING_LOSS_BURN_CONFIDENCE = 0.6

STAGE_LABELS = {
    "pre_revenue": "Pre-revenue",
    "cash_burning": "Revenue-generating, cash-burning",
    "cash_generative": "Cash-generative",
}

# Six headline figures per stage, in display order.
HEADLINE = {
    "pre_revenue": ["runway_quarters", "liquidity", "quarterly_burn", "research_development",
                    "rd_share_of_spend", "dilution_yoy"],
    "cash_burning": ["revenue", "runway_quarters", "free_cash_flow", "fcf_margin",
                     "rd_share_of_spend", "dilution_yoy"],
    "cash_generative": ["revenue", "free_cash_flow", "fcf_margin", "rd_intensity",
                        "liquidity", "dilution_yoy"],
}


@dataclass
class Figure:
    value: float | None
    unit: str                    # USD | ratio | quarters
    status: str                  # reported | derived | missing | not_meaningful
    source: str                  # provider name, or "derived" for computed figures
    confidence: float
    note: str | None
    inputs: list[str] = field(default_factory=list)


def _usable(metric) -> bool:
    return metric is not None and metric.value is not None and metric.status != "missing"


def _value(metrics: dict, concept: str) -> float | None:
    metric = metrics.get(concept)
    return metric.value if _usable(metric) else None


def _usd(value: float) -> str:
    size = abs(value)
    sign = "-" if value < 0 else ""
    if size >= 1e9:
        return f"{sign}${size / 1e9:.2f}B"
    if size >= 1e6:
        return f"{sign}${size / 1e6:.1f}M"
    return f"{sign}${size:,.0f}"


def _stored(metrics: dict, concept: str) -> Figure:
    """A figure that is a stored metric, keeping its own status and provenance."""
    metric = metrics.get(concept)
    if not _usable(metric):
        return Figure(None, "USD", "missing", "derived", 0.0, f"{concept} is not reported.", [concept])
    return Figure(metric.value, metric.unit or "USD", metric.status, metric.source,
                  metric.confidence, metric.quality_note, [concept])


def _computed(value: float | None, unit: str, inputs: list[str], parts: list, note: str,
              confidence_scale: float = 1.0) -> Figure:
    """A ratio or estimate computed from stored metrics; confidence is the weakest input's."""
    if value is None:
        return Figure(None, unit, "missing", "derived", 0.0, note, inputs)
    confidence = min((p.confidence for p in parts), default=1.0) * confidence_scale
    return Figure(value, unit, "derived", "derived", round(confidence, 3), note, inputs)


def _not_meaningful(unit: str, inputs: list[str], note: str) -> Figure:
    return Figure(None, unit, "not_meaningful", "derived", 0.0, note, inputs)


def classify_stage(metrics: dict) -> tuple[str, str]:
    """Deterministic lifecycle classification by economics, with the reason as text."""
    revenue = _value(metrics, "revenue")
    spend = (_value(metrics, "research_development") or 0.0) + (_value(metrics, "sga") or 0.0)
    if revenue is None or revenue <= 0:
        return "pre_revenue", "No revenue is reported."
    if spend > 0 and revenue < PRE_REVENUE_SPEND_RATIO * spend:
        return "pre_revenue", (
            f"Revenue of {_usd(revenue)} is {revenue / spend:.0%} of R&D plus SG&A "
            f"({_usd(spend)}), below the {PRE_REVENUE_SPEND_RATIO:.0%} threshold.")

    cash_flow = _value(metrics, "operating_cash_flow")
    if cash_flow is not None:
        if cash_flow > 0:
            return "cash_generative", f"Operating cash flow is positive ({_usd(cash_flow)})."
        return "cash_burning", (
            f"Revenue is material ({_usd(revenue)}) but operating cash flow is negative "
            f"({_usd(cash_flow)}).")

    operating_income = _value(metrics, "operating_income")
    if operating_income is not None:
        stage = "cash_generative" if operating_income > 0 else "cash_burning"
        return stage, (
            f"Operating cash flow is not reported; classified from operating income "
            f"({_usd(operating_income)}).")
    return "cash_burning", ("Neither operating cash flow nor operating income is reported, so "
                            "cash generation could not be determined; cash-burn figures are shown.")


def _burn(metrics: dict) -> tuple[float | None, list[str], list, str, float, bool]:
    """Average quarterly burn as (value, inputs, parts, note, confidence scale, burning).

    Prefers operating cash flow. Falls back to operating loss, flagged, when cash flow is
    not stored yet — e.g. metrics ingested before operating cash flow was normalized.
    """
    cash_flow = metrics.get("operating_cash_flow")
    if _usable(cash_flow):
        if cash_flow.value >= 0:
            return None, ["operating_cash_flow"], [cash_flow], (
                "Operating cash flow is positive, so the company is not burning cash."), 1.0, False
        return -cash_flow.value / 4, ["operating_cash_flow"], [cash_flow], (
            "Average quarterly burn: annual operating cash flow ÷ 4."), 1.0, True

    operating_income = metrics.get("operating_income")
    if _usable(operating_income):
        if operating_income.value >= 0:
            return None, ["operating_income"], [operating_income], (
                "Operating income is positive, so the company is not burning cash."), 1.0, False
        return -operating_income.value / 4, ["operating_income"], [operating_income], (
            "Estimated from operating loss ÷ 4 because operating cash flow is not available. "
            "Operating loss includes non-cash costs, so this likely overstates burn."
        ), OPERATING_LOSS_BURN_CONFIDENCE, True
    return None, ["operating_cash_flow"], [], "Burn cannot be estimated: no cash flow data.", 1.0, False


def _liquidity_parts(metrics: dict) -> tuple[object | None, str, str]:
    """(metric, concept, note) for liquidity, falling back to cash when not yet stored."""
    liquidity = metrics.get("liquidity")
    if _usable(liquidity):
        return liquidity, "liquidity", "Liquidity (cash plus marketable securities)"
    cash = metrics.get("cash")
    if _usable(cash):
        return cash, "cash", ("Cash only — marketable securities are not available for this "
                              "company yet, so runway is likely understated. Refresh the company.")
    return None, "liquidity", "Liquidity is not reported"


def _runway(metrics: dict) -> Figure:
    burn, burn_inputs, burn_parts, burn_note, scale, burning = _burn(metrics)
    funds, funds_concept, funds_note = _liquidity_parts(metrics)
    inputs = [funds_concept, *burn_inputs]
    if not burning:
        if burn_parts:
            return _not_meaningful("quarters", inputs, f"{burn_note} Runway does not constrain funding.")
        return _computed(None, "quarters", inputs, [], burn_note)
    if funds is None:
        return _computed(None, "quarters", inputs, [], f"{funds_note}; runway cannot be computed.")
    return _computed(funds.value / burn, "quarters", inputs, [funds, *burn_parts],
                     f"{funds_note} ÷ quarterly burn. {burn_note}", scale)


def _quarterly_burn(metrics: dict) -> Figure:
    burn, inputs, parts, note, scale, burning = _burn(metrics)
    if not burning and parts:
        return _not_meaningful("USD", inputs, note)
    return _computed(burn, "USD", inputs, parts, note, scale)


def _revenue_ratio(metrics: dict, stage: str, numerator: str, label: str, formula: str) -> Figure:
    """numerator ÷ revenue, withheld for pre-revenue companies where it is meaningless."""
    inputs = [numerator, "revenue"]
    if stage == "pre_revenue":
        return _not_meaningful("ratio", inputs, (
            f"{label} is not meaningful: revenue is too small relative to spending."))
    top, revenue = metrics.get(numerator), metrics.get("revenue")
    if not (_usable(top) and _usable(revenue)) or revenue.value <= 0:
        return _computed(None, "ratio", inputs, [], f"{label} needs {formula} inputs.")
    return _computed(top.value / revenue.value, "ratio", inputs, [top, revenue],
                     f"{label} = {formula}.")


def _rd_share_of_spend(metrics: dict) -> Figure:
    rd, sga = metrics.get("research_development"), metrics.get("sga")
    inputs = ["research_development", "sga"]
    if not (_usable(rd) and _usable(sga)) or rd.value + sga.value <= 0:
        return _computed(None, "ratio", inputs, [], "R&D share of spend needs R&D and SG&A.")
    return _computed(rd.value / (rd.value + sga.value), "ratio", inputs, [rd, sga],
                     "R&D ÷ (R&D + SG&A): share of operating spend going to the pipeline. "
                     "Excludes cost of goods, so it compares across pre-revenue and commercial companies.")


def _dilution(metrics: dict, prior: dict) -> Figure:
    shares, previous = metrics.get("shares_outstanding"), prior.get("shares_outstanding")
    inputs = ["shares_outstanding"]
    if not _usable(shares):
        return _computed(None, "ratio", inputs, [], "Shares outstanding are not reported.")
    if not _usable(previous) or previous.value <= 0:
        return _computed(None, "ratio", inputs, [], "No prior-year share count to compare against.")
    return _computed(shares.value / previous.value - 1, "ratio", inputs, [shares, previous],
                     "Year-over-year change in shares outstanding (cover-page counts).")


def build_profile(metrics: dict, prior: dict | None = None, fiscal_year: int | None = None) -> dict:
    """Classify the company and compute its biotech figures from stored metrics.

    `metrics` and `prior` map concept → stored metric for the latest and previous fiscal
    years. Any object with value / status / source / confidence / quality_note / unit works.
    """
    prior = prior or {}
    stage, reason = classify_stage(metrics)
    figures = {
        "revenue": _stored(metrics, "revenue"),
        "liquidity": _stored(metrics, "liquidity"),
        "free_cash_flow": _stored(metrics, "free_cash_flow"),
        "research_development": _stored(metrics, "research_development"),
        "quarterly_burn": _quarterly_burn(metrics),
        "runway_quarters": _runway(metrics),
        "fcf_margin": _revenue_ratio(metrics, stage, "free_cash_flow", "Free cash flow margin",
                                     "free cash flow ÷ revenue"),
        "rd_intensity": _revenue_ratio(metrics, stage, "research_development", "R&D intensity",
                                       "R&D ÷ revenue"),
        "rd_share_of_spend": _rd_share_of_spend(metrics),
        "dilution_yoy": _dilution(metrics, prior),
    }
    return {
        "fiscal_year": fiscal_year,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stage_reason": reason,
        "headline": HEADLINE[stage],
        "figures": {key: asdict(figure) for key, figure in figures.items()},
        "thresholds": {"pre_revenue_spend_ratio": PRE_REVENUE_SPEND_RATIO},
    }


def runway_quarters(metrics: dict) -> float | None:
    """Runway in quarters, or None when not burning cash or not computable."""
    figure = _runway(metrics)
    return round(figure.value, 2) if figure.value is not None else None
