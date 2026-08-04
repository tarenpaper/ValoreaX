"""Transparent, explainable signal engine (not a black box).

Every input maps to a *bounded, weighted* contribution with a plain-English
explanation, so a reviewer can see exactly how each factor moved the score. The
final label is a deterministic function of the score and a data-completeness
confidence — never a hidden model.

Scoring: contributions sum to a score in [-100, +100].
  * score >= +25 and confidence >= floor  → LONG
  * score <= -25 and confidence >= floor  → SHORT
  * otherwise                             → WATCHLIST

This is an educational research signal, not investment advice.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.models.common import SignalType

ENGINE_VERSION = "v1"

# Component weights (absolute max contribution of each). They sum to 100.
W_VALUATION = 35.0
W_CATALYST = 30.0
W_ABNORMAL_RETURN = 15.0
W_CASH_RUNWAY = 20.0

LONG_THRESHOLD = 25.0
SHORT_THRESHOLD = -25.0
CONFIDENCE_FLOOR = 0.35  # below this we refuse a directional call

# Full-strength reference points (where a factor hits its cap).
VALUATION_FULL_UPSIDE = 0.50   # +50% upside -> full positive valuation contribution
ABNORMAL_RETURN_FULL = 0.20    # +20% abnormal return -> full positive momentum contribution
RUNWAY_MIN_SAFE_QUARTERS = 4.0
RUNWAY_AMPLE_QUARTERS = 8.0

_OUTCOME_FACTOR = {
    "positive": 1.0,
    "negative": -1.0,
    "mixed": -0.3,
    "withdrawn": -0.6,
    "pending": 0.0,
}
_HIGH_IMPACT_EVENTS = {"pdufa", "adcomm", "phase_readout", "approval", "crl"}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class SignalInputs:
    valuation_upside: float | None = None       # fraction (0.30 = +30% vs. price)
    catalyst_outcome: str | None = None         # pending/positive/negative/mixed/withdrawn
    event_type: str | None = None               # catalyst type (scales resolved-outcome impact)
    days_to_next_catalyst: int | None = None     # proximity of the next expected catalyst
    abnormal_return: float | None = None        # recent return vs. benchmark, as a fraction
    cash_runway_quarters: float | None = None    # cash / quarterly burn
    manual_confidence: float | None = None       # analyst override, 0..1


@dataclass
class SignalComponent:
    name: str
    input_value: object
    weight: float
    contribution: float
    explanation: str


@dataclass
class SignalResult:
    signal: str
    score: float
    confidence: float
    components: list[dict]
    rationale: str
    engine_version: str = ENGINE_VERSION
    warnings: list[str] = field(default_factory=list)


def _valuation_component(upside: float | None) -> SignalComponent | None:
    if upside is None:
        return None
    factor = _clamp(upside / VALUATION_FULL_UPSIDE, -1.0, 1.0)
    contribution = factor * W_VALUATION
    return SignalComponent(
        name="valuation_upside",
        input_value=round(upside, 4),
        weight=W_VALUATION,
        contribution=round(contribution, 2),
        explanation=(
            f"DCF implies {upside:+.0%} vs. price; capped at ±{VALUATION_FULL_UPSIDE:.0%} "
            f"→ {contribution:+.1f}"
        ),
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


def _cash_runway_component(runway: float | None) -> SignalComponent | None:
    if runway is None:
        return None
    if runway < RUNWAY_MIN_SAFE_QUARTERS:
        factor = -_clamp((RUNWAY_MIN_SAFE_QUARTERS - runway) / RUNWAY_MIN_SAFE_QUARTERS, 0.0, 1.0)
        expl = f"Low cash runway (~{runway:.1f}q < {RUNWAY_MIN_SAFE_QUARTERS:.0f}q) → financing risk"
    elif runway > RUNWAY_AMPLE_QUARTERS:
        factor = 0.2
        expl = f"Ample cash runway (~{runway:.1f}q) → modest positive"
    else:
        factor = 0.0
        expl = f"Adequate cash runway (~{runway:.1f}q) → neutral"
    contribution = factor * W_CASH_RUNWAY
    return SignalComponent(
        name="cash_runway", input_value=round(runway, 2), weight=W_CASH_RUNWAY,
        contribution=round(contribution, 2), explanation=f"{expl} ({contribution:+.1f})",
    )


def _confidence(inputs: SignalInputs) -> tuple[float, list[str]]:
    directional = [
        inputs.valuation_upside, inputs.catalyst_outcome,
        inputs.abnormal_return, inputs.cash_runway_quarters,
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
    if inputs.manual_confidence is not None:
        conf = base_conf * _clamp(inputs.manual_confidence, 0.0, 1.0)
        warnings.append(
            f"Confidence scaled by analyst override ({inputs.manual_confidence:.0%})."
        )
    else:
        conf = base_conf
    if present < 2:
        warnings.append("Fewer than 2 directional inputs supplied; confidence is limited.")
    return round(_clamp(conf, 0.0, 1.0), 3), warnings


def score_signal(inputs: SignalInputs) -> SignalResult:
    """Compute an explainable LONG/SHORT/WATCHLIST signal from the given inputs."""
    components = [
        c for c in (
            _valuation_component(inputs.valuation_upside),
            _catalyst_component(inputs.catalyst_outcome, inputs.event_type),
            _abnormal_return_component(inputs.abnormal_return),
            _cash_runway_component(inputs.cash_runway_quarters),
        ) if c is not None
    ]
    score = round(sum(c.contribution for c in components), 2)
    confidence, warnings = _confidence(inputs)

    if confidence < CONFIDENCE_FLOOR:
        signal = SignalType.WATCHLIST.value
        decision = (
            f"Confidence {confidence:.0%} is below the {CONFIDENCE_FLOOR:.0%} floor → "
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
    )
