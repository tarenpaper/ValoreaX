"""Transparent, explainable signal engine (not a black box).

Every input maps to a *bounded, weighted* contribution with a plain-English
explanation, so a reviewer can see exactly how each factor moved the score. The
final label is a deterministic function of the score and a data-completeness
confidence — never a hidden model.

Scoring: contributions sum to a score in [-100, +100].
  * score >= +25 and confidence >= floor  → LONG
  * score <= -25 and confidence >= floor  → SHORT
  * otherwise                             → WATCHLIST

Two rules keep the engine honest about valuation. First, no input may reach the
score through two components at once: analyst coverage drives `analyst_consensus`
and nothing else. Second, the drug valuation is read **relatively**. A sum-of-the-parts
rNPV deliberately excludes terminal value, platform value and unvalued pipeline, so
price ÷ SOTP sits above 1× for almost every company; an absolute threshold would call
the whole market overvalued. The component scores the deviation from a reference
multiple and always names which reference it used.

This is an educational research signal, not investment advice.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.models.common import SignalType

ENGINE_VERSION = "v4"

# Component weights (absolute max contribution of each). They sum to 100.
W_VALUATION = 25.0
W_CATALYST = 20.0
W_EXCLUSIVITY = 15.0
W_FINANCIAL_HEALTH = 15.0
W_ANALYST = 15.0
W_ABNORMAL_RETURN = 5.0
W_NEWS = 5.0

LONG_THRESHOLD = 25.0
SHORT_THRESHOLD = -25.0
CONFIDENCE_FLOOR = 0.35  # below this we refuse a directional call

# Full-strength reference points (where a factor hits its cap).
VALUATION_FULL_UPSIDE = 0.50          # a manual +50% upside -> full positive contribution
RELATIVE_VALUATION_FULL_DEVIATION = 0.40  # 40% below the reference multiple -> full positive
ABNORMAL_RETURN_FULL = 0.20           # +20% abnormal return -> full positive momentum
RUNWAY_MIN_SAFE_QUARTERS = 4.0
RUNWAY_AMPLE_QUARTERS = 8.0
FCF_MARGIN_FULL = 0.25                # ±25% free cash flow margin -> full contribution
DILUTION_FULL = 0.20                  # +20% share growth -> full negative contribution

# Exclusivity: years of revenue-weighted patent life remaining.
CLIFF_YEARS = 3.0      # at or below this, the cliff is imminent -> full negative
SECURE_YEARS = 10.0    # at or above this, exclusivity is not the story -> full positive
PIPELINE_OFFSET_MAX = 0.3  # pipeline value share can offset this much of a cliff

# Value concentrated in one drug does not change the direction, only our certainty.
CONCENTRATION_HIGH = 0.60
CONCENTRATION_MAX_HAIRCUT = 0.20

_OUTCOME_FACTOR = {
    "positive": 1.0,
    "negative": -1.0,
    "mixed": -0.3,
    "withdrawn": -0.6,
    "pending": 0.0,
}
_HIGH_IMPACT_EVENTS = {"pdufa", "adcomm", "phase_readout", "approval", "crl"}

# How the valuation component read the price: which reference the multiple was
# compared against, or that an explicit upside was supplied instead.
BASIS_MANUAL = "manual_upside"
BASIS_PEER = "peer_median"
BASIS_OWN_RANGE = "own_range"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


@dataclass
class SignalInputs:
    # --- Valuation: an explicit upside wins; otherwise a multiple vs its reference ---
    valuation_upside: float | None = None        # fraction (0.30 = +30% vs. price), manual
    valuation_multiple: float | None = None      # price ÷ sum-of-the-parts value per share
    valuation_reference: float | None = None     # the multiple this one is judged against
    valuation_basis: str | None = None           # peer_median | own_range
    valuation_basis_detail: str | None = None    # e.g. "3 peers", "62 daily closes"

    catalyst_outcome: str | None = None          # pending/positive/negative/mixed/withdrawn
    event_type: str | None = None                # catalyst type (scales resolved-outcome impact)
    days_to_next_catalyst: int | None = None     # proximity of the next expected catalyst
    abnormal_return: float | None = None         # recent return vs benchmark, as a fraction
    analyst_consensus: float | None = None       # rating tilt, -1 (Strong Sell)..+1 (Strong Buy)
    analyst_label: str | None = None             # human label for the explanation (display only)

    # --- Financial health (stage-aware; whichever figures the filings support) ---
    cash_runway_quarters: float | None = None    # liquidity ÷ quarterly burn
    fcf_margin: float | None = None              # free cash flow ÷ revenue
    dilution_yoy: float | None = None            # share-count growth, +0.10 = 10% dilution

    # --- Drug structure, from the sum-of-the-parts valuation ---
    exclusivity_years: float | None = None       # revenue-weighted years to loss of exclusivity
    pipeline_value_share: float | None = None    # risk-adjusted pipeline ÷ total drug value
    value_concentration: float | None = None     # largest drug's share of drug value
    top_asset_name: str | None = None            # display only, for the concentration warning

    # --- News (labelled heuristic, high-impact articles only) ---
    news_sentiment: float | None = None          # method-weighted mean sentiment, -1..+1
    news_article_count: int | None = None

    manual_confidence: float | None = None       # analyst override, 0..1


@dataclass
class SignalComponent:
    name: str
    input_value: object
    weight: float
    contribution: float
    explanation: str
    basis: str | None = None


@dataclass
class SignalResult:
    signal: str
    score: float
    confidence: float
    components: list[dict]
    rationale: str
    engine_version: str = ENGINE_VERSION
    warnings: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def _valuation_component(inputs: SignalInputs) -> SignalComponent | None:
    """Price against value: an explicit upside, else the multiple vs its reference.

    The relative reading is the point. A sum-of-the-parts rNPV carries no terminal
    value, so price ÷ SOTP is above 1× nearly everywhere; what matters is whether this
    company trades below or above the premium its peers (or its own recent history)
    carry.
    """
    if inputs.valuation_upside is not None:
        upside = inputs.valuation_upside
        factor = _clamp(upside / VALUATION_FULL_UPSIDE, -1.0, 1.0)
        contribution = factor * W_VALUATION
        return SignalComponent(
            name="valuation", input_value=round(upside, 4), weight=W_VALUATION,
            contribution=round(contribution, 2), basis=BASIS_MANUAL,
            explanation=(f"Supplied upside {upside:+.0%} vs. price; capped at "
                         f"±{VALUATION_FULL_UPSIDE:.0%} → {contribution:+.1f}"),
        )

    multiple, reference = inputs.valuation_multiple, inputs.valuation_reference
    if multiple is None or not reference or multiple <= 0:
        return None

    # Positive deviation = trading below the reference premium = cheap.
    deviation = 1.0 - multiple / reference
    factor = _clamp(deviation / RELATIVE_VALUATION_FULL_DEVIATION, -1.0, 1.0)
    contribution = factor * W_VALUATION
    # Read out the premium over the reference rather than the deviation: past twice the
    # reference the deviation runs below -100%, which reads as nonsense.
    premium = multiple / reference - 1.0
    stance = "above" if premium >= 0 else "below"
    detail = f", {inputs.valuation_basis_detail}" if inputs.valuation_basis_detail else ""
    where = ("the peer median" if inputs.valuation_basis == BASIS_PEER
             else "its own trailing median")
    tail = ("" if inputs.valuation_basis == BASIS_PEER else
            " Sum-of-the-parts value is near-constant between 10-Ks, so this reads as price"
            " mean reversion.")
    return SignalComponent(
        name="valuation", input_value=round(multiple, 3), weight=W_VALUATION,
        contribution=round(contribution, 2), basis=inputs.valuation_basis,
        explanation=(f"Trades at {multiple:.2f}× sum-of-the-parts value, {abs(premium):.0%} "
                     f"{stance} {where} of {reference:.2f}×{detail} → "
                     f"{contribution:+.1f}.{tail}"),
    )


def _catalyst_component(outcome: str | None, event_type: str | None) -> SignalComponent | None:
    if outcome is None:
        return None
    base = _OUTCOME_FACTOR.get(outcome.lower(), 0.0)
    high_impact = (event_type or "").lower() in _HIGH_IMPACT_EVENTS
    mult = 1.2 if high_impact else 1.0
    factor = _clamp(base * mult, -1.0, 1.0)
    contribution = factor * W_CATALYST
    if outcome.lower() == "pending":
        expl = (
            f"Catalyst pending ({event_type or 'n/a'}) → 0.0 (no directional view until it resolves)"
        )
    else:
        expl = (
            f"Catalyst outcome '{outcome}'"
            + (f" on high-impact {event_type} (×1.2)" if high_impact else "")
            + f" → {contribution:+.1f}"
        )
    return SignalComponent(
        name="catalyst_outcome", input_value=outcome, weight=W_CATALYST,
        contribution=round(contribution, 2), explanation=expl,
    )


def _analyst_component(consensus: float | None, label: str | None) -> SignalComponent | None:
    if consensus is None:
        return None
    factor = _clamp(consensus, -1.0, 1.0)
    contribution = factor * W_ANALYST
    lbl = f" '{label}'" if label else ""
    return SignalComponent(
        name="analyst_consensus",
        input_value=round(consensus, 3),
        weight=W_ANALYST,
        contribution=round(contribution, 2),
        explanation=f"Analyst consensus{lbl} (rating tilt {consensus:+.2f}) → {contribution:+.1f}",
    )


def _abnormal_return_component(ar: float | None) -> SignalComponent | None:
    if ar is None:
        return None
    factor = _clamp(ar / ABNORMAL_RETURN_FULL, -1.0, 1.0)
    contribution = factor * W_ABNORMAL_RETURN
    return SignalComponent(
        name="abnormal_return", input_value=round(ar, 4), weight=W_ABNORMAL_RETURN,
        contribution=round(contribution, 2),
        explanation=f"Recent abnormal return {ar:+.0%} → {contribution:+.1f}",
    )


def _exclusivity_component(years: float | None, pipeline_share: float | None) -> SignalComponent | None:
    """Revenue-weighted years of patent life left, softened by pipeline value.

    A company earning most of its value from a drug that loses exclusivity in two years
    is structurally different from one with a decade of protection, and no other
    component sees that.
    """
    if years is None:
        return None
    span = SECURE_YEARS - CLIFF_YEARS
    factor = _clamp((years - CLIFF_YEARS) / span * 2.0 - 1.0, -1.0, 1.0)
    offset = 0.0
    if pipeline_share:
        # Pipeline value only helps a company facing a cliff; it never adds to a company
        # whose marketed drugs are already secure.
        offset = _clamp(pipeline_share, 0.0, 1.0) * PIPELINE_OFFSET_MAX
        factor = _clamp(factor + offset, -1.0, 1.0)
    contribution = factor * W_EXCLUSIVITY
    if years <= CLIFF_YEARS:
        state = f"Exclusivity cliff is close (~{years:.1f}y of revenue-weighted patent life)"
    elif years >= SECURE_YEARS:
        state = f"Exclusivity runs long (~{years:.1f}y revenue-weighted)"
    else:
        state = f"~{years:.1f}y of revenue-weighted exclusivity remaining"
    tail = (f"; pipeline carries {pipeline_share:.0%} of drug value (+{offset:.2f})"
            if round(offset, 2) else "")
    return SignalComponent(
        name="exclusivity_runway", input_value=round(years, 2), weight=W_EXCLUSIVITY,
        contribution=round(contribution, 2),
        explanation=f"{state}{tail} → {contribution:+.1f}",
    )


def _financial_health_component(inputs: SignalInputs) -> SignalComponent | None:
    """Balance sheet and burn, using whichever figures the company's stage supports.

    A pre-revenue company is judged on runway; a cash-generative one has no burn to
    divide by, so its free cash flow margin stands in. Dilution counts either way.
    """
    parts: list[float] = []
    notes: list[str] = []

    runway = inputs.cash_runway_quarters
    if runway is not None:
        if runway < RUNWAY_MIN_SAFE_QUARTERS:
            sub = -_clamp((RUNWAY_MIN_SAFE_QUARTERS - runway) / RUNWAY_MIN_SAFE_QUARTERS, 0.0, 1.0)
            notes.append(f"low runway ~{runway:.1f}q (financing risk)")
        elif runway > RUNWAY_AMPLE_QUARTERS:
            sub = 0.2
            notes.append(f"ample runway ~{runway:.1f}q")
        else:
            sub = 0.0
            notes.append(f"adequate runway ~{runway:.1f}q")
        parts.append(sub)
    elif inputs.fcf_margin is not None:
        # No meaningful runway means the company is not burning: judge it on margin.
        sub = _clamp(inputs.fcf_margin / FCF_MARGIN_FULL, -1.0, 1.0)
        notes.append(f"free cash flow margin {inputs.fcf_margin:+.0%}")
        parts.append(sub)

    if inputs.dilution_yoy is not None:
        sub = _clamp(-inputs.dilution_yoy / DILUTION_FULL, -1.0, 1.0)
        notes.append(f"share count {inputs.dilution_yoy:+.1%} YoY")
        parts.append(sub)

    if not parts:
        return None
    factor = _clamp(_mean(parts), -1.0, 1.0)
    contribution = factor * W_FINANCIAL_HEALTH
    return SignalComponent(
        name="financial_health",
        input_value={"runway_quarters": inputs.cash_runway_quarters,
                     "fcf_margin": inputs.fcf_margin, "dilution_yoy": inputs.dilution_yoy},
        weight=W_FINANCIAL_HEALTH, contribution=round(contribution, 2),
        explanation=f"{'; '.join(notes)} → {contribution:+.1f}",
    )


def _news_component(sentiment: float | None, count: int | None) -> SignalComponent | None:
    """High-impact news only, at low weight, and labelled as the heuristic it is."""
    if sentiment is None or not count:
        return None
    factor = _clamp(sentiment, -1.0, 1.0)
    contribution = factor * W_NEWS
    return SignalComponent(
        name="news_sentiment", input_value=round(sentiment, 3), weight=W_NEWS,
        contribution=round(contribution, 2),
        explanation=(f"{count} high-impact article{'s' if count != 1 else ''}, weighted sentiment "
                     f"{sentiment:+.2f} → {contribution:+.1f} (classification is a labelled "
                     f"heuristic, not a verified read)"),
    )


def _concentration_haircut(inputs: SignalInputs) -> tuple[float, str | None]:
    """Value concentrated in one drug lowers certainty, never direction."""
    share = inputs.value_concentration
    if share is None or share <= CONCENTRATION_HIGH:
        return 1.0, None
    over = (share - CONCENTRATION_HIGH) / (1.0 - CONCENTRATION_HIGH)
    scale = 1.0 - CONCENTRATION_MAX_HAIRCUT * _clamp(over, 0.0, 1.0)
    drug = inputs.top_asset_name or "one drug"
    return scale, (f"{share:.0%} of modelled drug value sits in {drug}; confidence reduced "
                   f"by {(1 - scale):.0%}.")


def _confidence(inputs: SignalInputs) -> tuple[float, list[str]]:
    directional = [
        inputs.valuation_upside if inputs.valuation_upside is not None else inputs.valuation_multiple,
        inputs.catalyst_outcome, inputs.analyst_consensus, inputs.abnormal_return,
        inputs.cash_runway_quarters if inputs.cash_runway_quarters is not None else inputs.fcf_margin,
        inputs.exclusivity_years, inputs.news_sentiment,
    ]
    present = sum(1 for v in directional if v is not None)
    completeness = present / len(directional)

    proximity_boost = 0.0
    d = inputs.days_to_next_catalyst
    if d is not None:
        if d <= 30:
            proximity_boost = 0.15
        elif d <= 90:
            proximity_boost = 0.10
        elif d <= 180:
            proximity_boost = 0.05

    base_conf = _clamp(0.15 + 0.6 * completeness + proximity_boost, 0.0, 1.0)
    warnings: list[str] = []

    scale, concentration_warning = _concentration_haircut(inputs)
    conf = base_conf * scale
    if concentration_warning:
        warnings.append(concentration_warning)

    if inputs.manual_confidence is not None:
        conf *= _clamp(inputs.manual_confidence, 0.0, 1.0)
        warnings.append(
            f"Confidence scaled by analyst override ({inputs.manual_confidence:.0%})."
        )
    if present < 2:
        warnings.append("Fewer than 2 directional inputs supplied; confidence is limited.")
    return round(_clamp(conf, 0.0, 1.0), 3), warnings


def _skipped(components: list[SignalComponent], inputs: SignalInputs) -> list[dict]:
    """Name the components that could not be computed, and why.

    A missing factor is not a neutral one. Saying so keeps a thin signal from reading
    like a complete one.
    """
    produced = {c.name for c in components}
    reasons = {
        "valuation": ("No sum-of-the-parts value per share and current price to compare, and no "
                      "upside was supplied."),
        "catalyst_outcome": "No catalyst on file for this company.",
        "exclusivity_runway": "No drug could be valued, so there is no exclusivity to weight.",
        "financial_health": "Filings supplied no runway, margin or share-count change.",
        "analyst_consensus": "No analyst coverage on file.",
        "abnormal_return": "Not enough aligned price history against the benchmark.",
        "news_sentiment": "No high-impact article in the window.",
    }
    return [{"name": name, "reason": reason}
            for name, reason in reasons.items() if name not in produced]


def score_signal(inputs: SignalInputs) -> SignalResult:
    """Compute an explainable LONG/SHORT/WATCHLIST signal from the given inputs."""
    components = [
        c for c in (
            _valuation_component(inputs),
            _catalyst_component(inputs.catalyst_outcome, inputs.event_type),
            _exclusivity_component(inputs.exclusivity_years, inputs.pipeline_value_share),
            _financial_health_component(inputs),
            _analyst_component(inputs.analyst_consensus, inputs.analyst_label),
            _abnormal_return_component(inputs.abnormal_return),
            _news_component(inputs.news_sentiment, inputs.news_article_count),
        ) if c is not None
    ]
    score = round(sum(c.contribution for c in components), 2)
    confidence, warnings = _confidence(inputs)

    if confidence < CONFIDENCE_FLOOR:
        signal = SignalType.WATCHLIST.value
        decision = (
            f"Confidence {confidence:.1%} is below the {CONFIDENCE_FLOOR:.0%} floor → "
            f"WATCHLIST regardless of score ({score:+.1f})."
        )
    elif score >= LONG_THRESHOLD:
        signal = SignalType.LONG.value
        decision = f"Score {score:+.1f} ≥ +{LONG_THRESHOLD:.0f} → LONG."
    elif score <= SHORT_THRESHOLD:
        signal = SignalType.SHORT.value
        decision = f"Score {score:+.1f} ≤ {SHORT_THRESHOLD:.0f} → SHORT."
    else:
        signal = SignalType.WATCHLIST.value
        decision = (
            f"Score {score:+.1f} is between {SHORT_THRESHOLD:.0f} and +{LONG_THRESHOLD:.0f} "
            f"→ WATCHLIST."
        )

    rationale_lines = [c.explanation for c in components] + [decision]
    rationale = "\n".join(rationale_lines)

    return SignalResult(
        signal=signal, score=score, confidence=confidence,
        components=[asdict(c) for c in components], rationale=rationale,
        engine_version=ENGINE_VERSION, warnings=warnings,
        skipped=_skipped(components, inputs),
    )
