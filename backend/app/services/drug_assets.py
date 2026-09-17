"""Turn SEC product lines and filing extraction into the drugs the valuation models.

Three jobs, all deterministic:

* **Assembly.** Marketed and royalty drugs come from XBRL product lines; pipeline
  programmes come from the 10-K's own text. A programme that is really a marketed drug
  under study for a *new* indication stays separate (suzetrigine is sold as JOURNAVX for
  acute pain and is in Phase 3 for diabetic neuropathy) — it is a genuine second asset,
  not a duplicate.
* **Peak sales.** SEC never states them, so they are derived: the indication's disclosed
  patient population × what the company already earns per patient on its established
  drugs. Both numbers are quoted from the filing. Where either is missing the programme is
  left unvalued rather than guessed.
* **Growth.** Trailing growth from the product's own revenue history, capped.

The analog carries an obvious risk — a company whose current drugs dominate a small,
high-priced market will imply a high rate for a new indication — so the rate, its inputs
and a warning when the result exceeds the company's biggest product all travel with the
value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.drug_aliases import expand_aliases, strip_biologic_suffix
from app.services.rnpv_benchmarks import (
    MAX_TRAILING_GROWTH,
    MIN_TRAILING_GROWTH,
    REVIEW_YEARS,
    YEARS_TO_PEAK,
    probability_for,
    years_to_launch,
)

# A drug's indication counts as established once it has this many years of reported sales.
ESTABLISHED_YEARS = 3

# Stamped into every asset. Filings do not change, so a sync normally skips once an
# accession is stored — but when the *shape* of what we extract changes, already-stored
# assets are stale in a way the accession cannot express. Bump this and they rebuild.
ASSET_BUILD_VERSION = 4

# Why a programme carries no value. The code decides whether a continuing value may stand
# in for it later; the text is what the user reads.
NO_POPULATION = "no_population"          # the filing simply does not disclose one
NO_ANALOG = "no_analog"                  # the company has no established drug to rate against
ALREADY_SERVED = "already_served"        # its patients are counted in a marketed drug already
NO_SUCCESS_RATE = "no_success_rate"      # no published probability applies to this stage
# Cannibalisation and missing probabilities are real absences of value, not gaps in the
# filing, so no continuing value may be substituted for them.
CONTINUING_VALUE_ELIGIBLE = (NO_POPULATION, NO_ANALOG)


def normalize(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def asset_key(name: str, indication: str | None = None) -> str:
    """Identity for idempotent sync: the same drug in a new indication is a new asset."""
    return f"{normalize(name)}|{normalize(indication)}"[:128]


# Filings name one drug several ways at once: a patent table lists "Mounjaro/ Zepbound"
# where the XBRL revenue table has separate "Mounjaro" and "Zepbound" lines.
_COMBINED_NAME = re.compile(r"\s*[/,]\s*")
_MIN_FRAGMENT = 3


def _alias_set(name: str, extra: list[str] | None = None) -> set[str]:
    names = {name, *(extra or [])}
    for value in list(names):
        names |= expand_aliases(value)
        # Keep the combined form too, so a label written the same way in both tables
        # ("TRIKAFTA/KAFTRIO") still matches itself.
        names |= {part for part in _COMBINED_NAME.split(value)
                  if len(normalize(part)) >= _MIN_FRAGMENT}
    return {normalize(n) for n in names if n}


# A filing introduces a programme in full and then refers to it in shorthand — Gilead's
# 10-K names "sacituzumab govitecan-hziy" and later just "SG". Left alone the shorthand
# becomes a programme of its own, inflating the pipeline and defeating alias matching.
MAX_SHORTHAND_CHARS = 4
MIN_PREFIX_CHARS = 3


def _abbreviates(short: str, full: str) -> bool:
    """Is `short` an initialism of `full`, or a prefix of it?"""
    # The FDA suffix would otherwise count as a word, making "sacituzumab govitecan-hziy"
    # initialise to SGH rather than the SG the filing actually uses.
    full = strip_biologic_suffix(full)
    words = [w for w in re.split(r"[^A-Za-z0-9]+", full) if w]
    if len(words) > 1 and short == normalize("".join(w[0] for w in words)):
        return True
    full_key = normalize(full)
    return len(short) >= MIN_PREFIX_CHARS and full_key != short and full_key.startswith(short)


def canonical_name(name: str, others: list[str]) -> str:
    """Expand a shorthand programme name to the full one it stands for.

    Only when exactly one candidate matches: an ambiguous abbreviation is left alone
    rather than guessed at.
    """
    short = normalize(name)
    if not short or len(short) > MAX_SHORTHAND_CHARS:
        return name
    matches = {normalize(other): other for other in others
               if normalize(other) != short and _abbreviates(short, other)}
    return next(iter(matches.values())) if len(matches) == 1 else name


def indications_match(left: str | None, right: str | None) -> bool:
    a, b = normalize(left), normalize(right)
    return bool(a and b and (a == b or a in b or b in a))


def trailing_growth(years: dict[int, float]) -> float:
    """Compound growth across the reported years, capped before being projected."""
    if len(years) < 2:
        return 0.0
    ordered = sorted(years)
    first, last = years[ordered[0]], years[ordered[-1]]
    if first <= 0 or last <= 0:
        return 0.0
    growth = (last / first) ** (1 / (ordered[-1] - ordered[0])) - 1
    return max(MIN_TRAILING_GROWTH, min(MAX_TRAILING_GROWTH, growth))


@dataclass
class AnalogRate:
    rate: float | None                 # revenue per addressable patient
    revenue: float = 0.0
    patients: float = 0.0
    indications: tuple[str, ...] = ()
    geography_note: str | None = None
    reason: str | None = None          # why no rate could be derived


def analog_rate(product_lines: list, marketed: list[dict], populations: list[dict]) -> AnalogRate:
    """Revenue per patient from the company's established drugs.

    Only indications the company has sold into for `ESTABLISHED_YEARS` count: a drug in its
    launch year earns a fraction of what it eventually will, and would understate the rate.
    """
    established = [line for line in product_lines
                   if line.classification == "product" and len(line.years) >= ESTABLISHED_YEARS]
    if not established:
        return AnalogRate(None, reason=(
            f"No product has {ESTABLISHED_YEARS} years of reported revenue, so the company has "
            "no established drug to derive revenue per patient from."))
    if not populations:
        return AnalogRate(None, reason="The filing discloses no patient population to divide by.")

    # Group by indication first: several drugs can serve one patient population, and adding
    # that population once per drug would inflate the denominator.
    by_indication: dict[str, dict] = {}
    geography_mismatch = False
    for line in established:
        indication = next((m.get("indication") for m in marketed
                           if _alias_set(m["name"]) & _alias_set(line.label)), None)
        population = _best_population(indication, populations)
        if indication is None or population is None:
            continue
        latest = line.latest()
        # Compare like with like: a US population needs US revenue.
        if population["geography"] == "us" and latest.us_value is not None:
            revenue_for_line = latest.us_value
        else:
            revenue_for_line = latest.value
            geography_mismatch = geography_mismatch or population["geography"] == "us"
        entry = by_indication.setdefault(indication, {"revenue": 0.0, "patients": population["patients"]})
        entry["revenue"] += revenue_for_line

    revenue = sum(entry["revenue"] for entry in by_indication.values())
    patients = sum(entry["patients"] for entry in by_indication.values())
    matched = list(by_indication)

    if not patients:
        return AnalogRate(None, reason=(
            "No established drug could be matched to a disclosed patient population."))
    note = ("A US-only population was compared with worldwide revenue, which overstates the rate."
            if geography_mismatch else None)
    return AnalogRate(revenue / patients, revenue, patients, tuple(dict.fromkeys(matched)), note)


def _best_population(indication: str | None, populations: list[dict]) -> dict | None:
    """The best matching population for an indication.

    Revenue is worldwide, so a worldwide population is preferred; among equally suitable
    figures the smallest is taken, which is the conservative choice.
    """
    candidates = [p for p in populations if indications_match(indication, p.get("indication"))]
    if not candidates:
        return None
    return min(candidates, key=lambda p: (p.get("geography") != "worldwide", p["patients"]))


def peak_sales_for(indication: str | None, rate: AnalogRate, populations: list[dict],
                   largest_product: float | None,
                   served_indications: list[str | None] | None = None) -> dict:
    """Derived peak sales for one programme, or the reason it cannot be derived."""
    # Those patients are already paying the company, and that revenue is already counted in
    # the marketed drug's own model. Valuing this programme on the same population would
    # add the franchise twice, so it is reported without a value instead.
    served = next((existing for existing in (served_indications or [])
                   if indications_match(indication, existing)), None)
    if served is not None:
        return {"peak_sales": None, "unvalued_code": ALREADY_SERVED,
                "unvalued_reason": (f"The company already sells into {served}, so this "
                                    f"programme's patients are counted in the marketed drug. "
                                    f"Valuing it on the same population would double count.")}
    if rate.rate is None:
        return {"peak_sales": None, "unvalued_reason": rate.reason, "unvalued_code": NO_ANALOG}
    population = _best_population(indication, populations)
    if population is None:
        return {"peak_sales": None, "unvalued_code": NO_POPULATION,
                "unvalued_reason": (f"The filing discloses no patient population for "
                                    f"{indication or 'this indication'}, so peak sales cannot be derived.")}
    peak = population["patients"] * rate.rate
    warning = None
    uncapped = None
    # The analog assumes a new drug monetises every patient as well as the company's current
    # franchise does — plausible only where that franchise is near-monopoly. Bounding the
    # result by the company's own largest product keeps the limit inside SEC data rather
    # than inventing a penetration rate, and the uncapped figure stays visible.
    if largest_product and peak > largest_product:
        uncapped, peak = peak, largest_product
        warning = (f"Derived peak sales of ${uncapped / 1e9:,.1f}B exceeded the company's largest "
                   f"current product, so they are capped at it. The analog assumes a new indication "
                   f"earns like the existing franchise, which usually overstates a new entrant.")
    return {"peak_sales": peak, "uncapped_peak_sales": uncapped, "patients": population["patients"],
            "population_geography": population["geography"], "population_quote": population.get("quote"),
            "rate": rate.rate, "rate_revenue": rate.revenue, "rate_patients": rate.patients,
            "rate_indications": list(rate.indications), "warning": warning or rate.geography_note}


def build_assets(product_lines: list, business: dict, today_year: int) -> list[dict]:
    """Marketed, royalty and pipeline drugs, each with its derived inputs and provenance."""
    marketed_items = business.get("marketed") or []
    populations = business.get("populations") or []
    rate = analog_rate(product_lines, marketed_items, populations)
    products = [line for line in product_lines if line.classification == "product"]
    largest = max((line.latest().value for line in products), default=None)

    assets: list[dict] = []
    marketed_index: list[tuple[set[str], str | None]] = []
    for line in products + [line for line in product_lines
                            if line.classification == "royalty_collaboration"]:
        latest = line.latest()
        indication = next((m.get("indication") for m in marketed_items
                           if _alias_set(m["name"]) & _alias_set(line.label)), None)
        kind = "marketed" if line.classification == "product" else "royalty"
        if kind == "marketed":
            marketed_index.append((_alias_set(line.label), indication))
        assets.append({
            "key": asset_key(line.label, indication), "name": line.label, "kind": kind,
            "origin": "sec_product_line", "xbrl_member": line.member, "indication": indication,
            "phase": "approved", "extracted": {
                "base_revenue": latest.value, "fiscal_year": latest.fiscal_year,
                "growth_rate": trailing_growth({y: v.value for y, v in line.years.items()}),
                "years_reported": sorted(line.years), "geography_basis": latest.geography_basis,
                "revenue_tag": latest.revenue_tag, "classification_reason": line.reason,
                "probability": 1.0, "build_version": ASSET_BUILD_VERSION},
        })

    program_names = [p["name"] for p in (business.get("pipeline") or []) if p.get("name")]
    programs = {}
    # Prefer the full-name record for conflicting fields, fill missing fields from other
    # mentions, and retain all aliases and quotes. Separate indications stay separate.
    mentions = sorted(business.get("pipeline") or [], key=lambda p:
                      p["name"] != canonical_name(p["name"], program_names))
    for mention in mentions:
        program = {**mention, "name": canonical_name(mention["name"], program_names)}
        key = asset_key(program["name"], program.get("indication"))
        if key not in programs:
            programs[key] = program
            continue
        primary = programs[key]
        for field, value in program.items():
            if not primary.get(field):
                primary[field] = value
        primary["aliases"] = sorted(set(primary.get("aliases") or [])
                                    | set(program.get("aliases") or []))
        primary["quote"] = "\n".join(dict.fromkeys(
            q for q in (primary.get("quote"), program.get("quote")) if q)) or None

    for program in programs.values():
        aliases = _alias_set(program["name"], program.get("aliases"))
        duplicate = next((ind for names, ind in marketed_index
                          if names & aliases and indications_match(ind, program.get("indication"))), None)
        if duplicate is not None:
            continue  # the same drug in the same indication is already modelled as marketed
        extension = any(names & aliases for names, _ in marketed_index)
        probability = probability_for(program["phase"])
        launch_gap = years_to_launch(program["phase"])
        derived = peak_sales_for(program.get("indication"), rate, populations, largest,
                                 [ind for _, ind in marketed_index])
        reason = derived.get("unvalued_reason")
        code = derived.get("unvalued_code")
        if probability is None:
            # Without a success rate the programme cannot be valued whatever its peak sales,
            # so that reason comes first.
            reason = ("No published success rate applies to a programme at this stage, "
                      "so it is listed without a value.")
            code = NO_SUCCESS_RATE
        assets.append({
            "key": asset_key(program["name"], program.get("indication")), "name": program["name"],
            "kind": "pipeline", "origin": "filing_pipeline", "xbrl_member": None,
            "indication": program.get("indication"), "phase": program["phase"],
            "extracted": {
                "peak_sales": derived.get("peak_sales"), "probability": probability,
                "launch_year": today_year + (launch_gap if launch_gap is not None else 0)
                + (REVIEW_YEARS if program.get("milestone") and program["phase"] == "filed" else 0),
                "years_to_peak": YEARS_TO_PEAK, "milestone": program.get("milestone"),
                "quote": program.get("quote"), "line_extension": extension,
                "unvalued_reason": reason, "unvalued_code": code,
                "build_version": ASSET_BUILD_VERSION,
                **{k: v for k, v in derived.items()
                   if k not in ("peak_sales", "unvalued_reason", "unvalued_code")},
            },
        })
    return assets
