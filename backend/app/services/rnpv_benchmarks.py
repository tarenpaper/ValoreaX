"""Published benchmarks used where SEC filings cannot supply a number.

These are the only inputs in the valuation that come from outside the filings, so they are
collected here, labelled, and overridable per drug rather than scattered through the model.

Sources and caveats:

* Probability of reaching market by phase comes from BIO / Informa / QLS, *Clinical
  Development Success Rates 2011-2020*: phase transitions of 52.0% (I→II), 28.9% (II→III),
  57.8% (III→filing) and 90.6% (filing→approval), which compound to the cumulative figures
  below. VERIFY against the published report before relying on these commercially; rates
  also vary widely by therapeutic area, which this does not model.
* A programme spanning two phases takes the earlier phase's probability, the conservative
  reading (a Phase 2/3 study is treated as Phase 2).
* Preclinical programmes have no published rate here and are deliberately left unvalued
  rather than assigned a made-up number.
* Years to launch and years to peak are planning conventions, not filing facts. VERIFY.
* A pipeline drug has no patent table entry yet, so its exclusivity is assumed to run a
  fixed number of years from launch. Without this a programme would plateau to the end of
  the horizon, which is the perpetual-value assumption this model exists to avoid. VERIFY.
* Post-exclusivity erosion is a heuristic. Small molecules face immediate generic entry;
  biologics erode more slowly. SEC data does not state a drug's modality, so the small
  molecule (faster erosion, lower value) is the default.
"""
from __future__ import annotations

# Cumulative probability that a programme at this phase reaches market.
PHASE_SUCCESS = {
    "phase_1": 0.079,
    "phase_1_2": 0.079,
    "phase_2": 0.151,
    "phase_2_3": 0.151,
    "phase_3": 0.524,
    "filed": 0.906,
    "approved": 1.0,
}

# Years from today to first sales.
YEARS_TO_LAUNCH = {
    "phase_1": 8,
    "phase_1_2": 8,
    "phase_2": 6,
    "phase_2_3": 5,
    "phase_3": 3,
    "filed": 1,
    "approved": 0,
}

# A regulator's review period, applied when a filing quotes a submission milestone.
REVIEW_YEARS = 1
YEARS_TO_PEAK = 5
# Exclusivity assumed for a pipeline drug whose expiry the filing does not state, counted
# from launch. Roughly a 20-year patent filed early in development, part of it consumed
# before approval.
EXCLUSIVITY_YEARS_FROM_LAUNCH = 12

# Share of pre-exclusivity revenue retained in each year after exclusivity ends.
EROSION = {
    "small_molecule": (0.35, 0.15, 0.08, 0.05),
    "biologic": (0.75, 0.55, 0.40, 0.30),
}
DEFAULT_MODALITY = "small_molecule"

DEFAULT_DISCOUNT_RATE = 0.10
# Nothing is projected beyond this, so a drug with no known exclusivity date cannot be
# valued in perpetuity by accident.
HORIZON_YEARS = 25

# Fallbacks when a filing does not give the company's own economics.
DEFAULT_GROSS_MARGIN = 0.80
DEFAULT_COMMERCIAL_COST_RATE = 0.25
US_STATUTORY_TAX_RATE = 0.21
MAX_EFFECTIVE_TAX_RATE = 0.35
# Trailing growth is capped before being projected forward.
MAX_TRAILING_GROWTH = 0.60
MIN_TRAILING_GROWTH = -0.30


def probability_for(phase: str | None) -> float | None:
    """Cumulative probability of reaching market, or None when there is no published rate."""
    return PHASE_SUCCESS.get(phase or "")


def years_to_launch(phase: str | None) -> int | None:
    return YEARS_TO_LAUNCH.get(phase or "")


def erosion_curve(modality: str | None) -> tuple[float, ...]:
    return EROSION.get(modality or DEFAULT_MODALITY, EROSION[DEFAULT_MODALITY])
