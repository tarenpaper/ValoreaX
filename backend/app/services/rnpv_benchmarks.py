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
* Development cost is charged **per programme by phase**, not by dividing the company's
  R&D budget across the programmes its 10-K happens to name. That allocation overcharged by
  roughly an order of magnitude: Lilly's $13.3B of R&D funds hundreds of programmes -
  preclinical, lifecycle, platform and manufacturing science - not the nine named in Item 1,
  so dividing it by nine charged each $1.48B a year and drove their value negative.
  The figures below are **order-of-magnitude planning numbers, not measured costs** -
  a late-stage programme typically runs several trials at once, which is why a phase costs
  far more per year than any single trial. VERIFY against your own source before relying
  on them.
* R&D beyond those programmes is deliberately **not** subtracted. The model also omits the
  future programmes that spending will create, so charging the cost without the benefit
  would be asymmetric - the same reasoning that keeps terminal value out.
* A programme the filing gives no patient population for is not worthless, it is
  undisclosed — and for most large pharma that is the whole pipeline. Its continuing value
  stands in with the company's own *median* marketed product as the peak-sales analog,
  halved. The median (not the mean) keeps one blockbuster from setting the bar, and the
  haircut reflects that this analog is weaker than a disclosed population: it assumes a new
  programme sells like an established drug, ignoring competition and smaller indications.
  It is reported on its own line, never folded into drug value. VERIFY the haircut against
  your own view before relying on it.
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

# Annual cost of running a programme at each phase, per programme.
DEVELOPMENT_COST_PER_YEAR = {
    "phase_1": 40e6,
    "phase_1_2": 60e6,
    "phase_2": 120e6,
    "phase_2_3": 200e6,
    "phase_3": 300e6,
    "filed": 30e6,       # the trials are done; this is submission and inspection support
    "approved": 0.0,
}
DEFAULT_DEVELOPMENT_COST_PER_YEAR = 120e6

# Applied to the median-product analog behind continuing value. Deliberately conservative:
# the model's job is to avoid overclaiming, and this basis is the weakest one it uses.
CONTINUING_VALUE_HAIRCUT = 0.5

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


def development_cost_for(phase: str | None) -> float:
    """Annual cost of running one programme at this phase."""
    return DEVELOPMENT_COST_PER_YEAR.get(phase or "", DEFAULT_DEVELOPMENT_COST_PER_YEAR)
