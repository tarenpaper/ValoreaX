"""Assembling drugs from SEC product lines and 10-K extraction, and deriving peak sales."""
from __future__ import annotations

import pytest

from app.services.drug_assets import (
    analog_rate,
    asset_key,
    build_assets,
    indications_match,
    peak_sales_for,
    trailing_growth,
)
from app.services.product_revenue import ProductLine, ProductYear


def line(label, values, classification="product", us=None, member=None):
    """values: {fiscal_year: worldwide revenue}."""
    years = {year: ProductYear(year, value, us, "product_only", "Revenues")
             for year, value in values.items()}
    return ProductLine(member=member or f"co:{label}Member", label=label,
                       classification=classification, reason="", years=years)


def population(indication, patients, geography="worldwide"):
    return {"indication": indication, "patients": patients, "geography": geography,
            "quote": f"approximately {patients:,} people with {indication}"}


TRIKAFTA = line("TRIKAFTA/KAFTRIO", {2023: 9_000e6, 2024: 9_800e6, 2025: 10_313e6})
ALYFTREK = line("ALYFTREK", {2023: 700e6, 2024: 780e6, 2025: 838e6})
CASGEVY = line("CASGEVY", {2024: 70e6, 2025: 116e6})            # only two years: not established
MARKETED = [{"name": "TRIKAFTA/KAFTRIO", "indication": "CF"}, {"name": "ALYFTREK", "indication": "CF"},
            {"name": "CASGEVY", "indication": "SCD"}]


# --- Analog rate --------------------------------------------------------------------
def test_one_population_serves_several_drugs_without_being_counted_twice():
    """Trikafta and Alyftrek both treat CF; the CF population must count once."""
    rate = analog_rate([TRIKAFTA, ALYFTREK], MARKETED, [population("CF", 112_000)])
    assert rate.patients == 112_000
    assert rate.revenue == pytest.approx(10_313e6 + 838e6)
    assert rate.rate == pytest.approx((10_313e6 + 838e6) / 112_000)
    assert rate.indications == ("CF",)


def test_worldwide_population_is_preferred_over_a_us_only_figure():
    populations = [population("CF", 97_000, "us"), population("CF", 112_000, "worldwide")]
    rate = analog_rate([TRIKAFTA], MARKETED, populations)
    assert rate.patients == 112_000          # matches the worldwide revenue basis


def test_us_population_is_paired_with_us_revenue_when_available():
    us_line = line("TRIKAFTA/KAFTRIO", {2023: 9_000e6, 2024: 9_800e6, 2025: 10_313e6}, us=6_000e6)
    rate = analog_rate([us_line], MARKETED, [population("CF", 97_000, "us")])
    assert rate.revenue == 6_000e6
    assert rate.geography_note is None

    # Without a US split the comparison is mismatched and must say so.
    mismatched = analog_rate([TRIKAFTA], MARKETED, [population("CF", 97_000, "us")])
    assert mismatched.revenue == 10_313e6
    assert "overstates" in mismatched.geography_note


def test_launch_stage_drugs_do_not_set_the_rate():
    """A drug in its launch year earns a fraction of its eventual sales."""
    rate = analog_rate([CASGEVY], MARKETED, [population("SCD", 60_000)])
    assert rate.rate is None
    assert "years of reported revenue" in rate.reason


def test_rate_is_refused_when_nothing_can_be_matched():
    assert analog_rate([TRIKAFTA], MARKETED, []).reason.startswith("The filing discloses no patient")
    unmatched = analog_rate([TRIKAFTA], MARKETED, [population("psoriasis", 500_000)])
    assert unmatched.rate is None
    assert "matched" in unmatched.reason


# --- Peak sales ----------------------------------------------------------------------
def test_peak_sales_are_patients_times_the_company_rate():
    rate = analog_rate([TRIKAFTA, ALYFTREK], MARKETED, [population("CF", 112_000)])
    derived = peak_sales_for("CF", rate, [population("CF", 112_000)], largest_product=None)
    assert derived["peak_sales"] == pytest.approx(112_000 * rate.rate)
    assert derived["uncapped_peak_sales"] is None
    assert derived["population_quote"]


def test_peak_sales_are_capped_by_the_largest_current_product():
    rate = analog_rate([TRIKAFTA, ALYFTREK], MARKETED, [population("CF", 112_000)])
    populations = [population("CF", 112_000), population("pMN", 600_000)]
    derived = peak_sales_for("pMN", rate, populations, largest_product=10_313e6)
    assert derived["peak_sales"] == 10_313e6
    assert derived["uncapped_peak_sales"] > 50e9          # ~$59.7B before the cap
    assert "capped" in derived["warning"]


def test_programmes_without_a_population_are_left_unvalued():
    rate = analog_rate([TRIKAFTA], MARKETED, [population("CF", 112_000)])
    derived = peak_sales_for("IgA nephropathy", rate, [population("CF", 112_000)], None)
    assert derived["peak_sales"] is None
    assert "no patient population for IgA nephropathy" in derived["unvalued_reason"]


def test_no_analog_means_no_peak_sales_anywhere():
    rate = analog_rate([CASGEVY], MARKETED, [population("SCD", 60_000)])
    derived = peak_sales_for("SCD", rate, [population("SCD", 60_000)], None)
    assert derived["peak_sales"] is None and derived["unvalued_reason"] == rate.reason


# --- Assembly ------------------------------------------------------------------------
def business(pipeline, populations=None):
    return {"pipeline": pipeline, "marketed": MARKETED,
            "populations": populations or [population("CF", 112_000)]}


def program(name, indication, phase="phase_3", **extra):
    return {"name": name, "aliases": extra.pop("aliases", []), "indication": indication,
            "phase": phase, "milestone": extra.pop("milestone", None), "quote": "q", **extra}


def test_marketed_and_royalty_lines_become_assets_with_growth():
    assets = build_assets([TRIKAFTA, line("Other revenues", {2025: 31e6}, "royalty_collaboration")],
                          business([]), 2026)
    trikafta = next(a for a in assets if a["name"] == "TRIKAFTA/KAFTRIO")
    assert trikafta["kind"] == "marketed" and trikafta["phase"] == "approved"
    assert trikafta["extracted"]["base_revenue"] == 10_313e6
    assert trikafta["extracted"]["growth_rate"] == pytest.approx(trailing_growth(
        {2023: 9_000e6, 2024: 9_800e6, 2025: 10_313e6}))
    assert any(a["kind"] == "royalty" for a in assets)


def test_a_marketed_drug_studied_in_a_new_indication_is_a_separate_asset():
    """Suzetrigine sells as JOURNAVX for acute pain and is in Phase 3 for neuropathy."""
    journavx = line("JOURNAVX", {2024: 20e6, 2025: 60e6})
    marketed = [*MARKETED, {"name": "JOURNAVX", "indication": "acute pain"}]
    filing = {"pipeline": [program("suzetrigine", "DPN", aliases=["VX-548"]),
                           program("suzetrigine", "acute pain")],
              "marketed": marketed, "populations": [population("CF", 112_000)]}
    assets = build_assets([TRIKAFTA, ALYFTREK, journavx], filing, 2026)
    pipeline = [a for a in assets if a["kind"] == "pipeline"]
    # The same drug in the same indication is already modelled as marketed.
    assert [a["indication"] for a in pipeline] == ["DPN"]
    assert pipeline[0]["extracted"]["line_extension"] is True


def test_pipeline_assets_carry_phase_probability_and_timing():
    filing = business([program("VX-670", "myotonic dystrophy", "phase_1_2")],
                      [population("CF", 112_000), population("myotonic dystrophy", 40_000)])
    assets = build_assets([TRIKAFTA, ALYFTREK], filing, 2026)
    program_asset = next(a for a in assets if a["kind"] == "pipeline")
    assert program_asset["extracted"]["probability"] == pytest.approx(0.079)
    assert program_asset["extracted"]["launch_year"] == 2026 + 8
    assert program_asset["extracted"]["peak_sales"] is not None


def test_a_programme_in_an_indication_the_company_already_sells_into_is_not_valued():
    """Those patients already pay the company; the marketed drug's model counts them."""
    assets = build_assets([TRIKAFTA, ALYFTREK], business([program("VX-522", "CF", "phase_1_2")]), 2026)
    next_generation = next(a for a in assets if a["kind"] == "pipeline")
    assert next_generation["extracted"]["peak_sales"] is None
    assert "double count" in next_generation["extracted"]["unvalued_reason"]
    # The marketed CF drugs keep their full value; only the successor is withheld.
    assert sum(1 for a in assets if a["kind"] == "marketed") == 2


def test_preclinical_programmes_are_listed_but_not_valued():
    assets = build_assets([TRIKAFTA, ALYFTREK],
                          business([program("early asset", "CF", "preclinical")]), 2026)
    early = next(a for a in assets if a["kind"] == "pipeline")
    assert early["extracted"]["probability"] is None
    assert "no published success rate" in early["extracted"]["unvalued_reason"].lower()


def test_keys_are_stable_and_separate_by_indication():
    assert asset_key("TRIKAFTA/KAFTRIO", "CF") == asset_key("trikafta kaftrio", "cf")
    assert asset_key("suzetrigine", "DPN") != asset_key("suzetrigine", "acute pain")


def test_indication_matching_is_tolerant_but_not_loose():
    assert indications_match("AMKD", "primary AMKD")
    assert indications_match("CF", "cf")
    assert not indications_match("CF", "IgAN")
    assert not indications_match(None, "CF")


def test_trailing_growth_is_capped_in_both_directions():
    assert trailing_growth({2023: 1.0, 2024: 100.0}) == 0.60      # capped
    assert trailing_growth({2023: 100.0, 2024: 1.0}) == -0.30     # floored
    assert trailing_growth({2025: 10.0}) == 0.0                   # a single year cannot grow


def test_a_patent_table_naming_two_brands_at_once_matches_either_revenue_line():
    """Lilly's patent table lists "Mounjaro/ Zepbound"; XBRL reports them separately."""
    from app.services.drug_assets import _alias_set
    combined = _alias_set("Mounjaro/ Zepbound")
    assert _alias_set("Mounjaro") & combined and _alias_set("Zepbound") & combined
    # The combined spelling still matches a line labelled the same way.
    assert _alias_set("TRIKAFTA/KAFTRIO") & _alias_set("TRIKAFTA/KAFTRIO")
    assert not _alias_set("Jardiance") & combined


def test_growth_uses_elapsed_years_when_history_has_gaps():
    assert trailing_growth({2022: 100, 2025: 133.1}) == pytest.approx(.10)


# --- One molecule, one name --------------------------------------------------------
def test_a_biologics_fda_suffix_does_not_hide_the_molecule():
    """Trodelvy is "sacituzumab govitecan-hziy" in the pipeline table and Trodelvy in the
    product table; the four-letter suffix is FDA housekeeping, not a different drug."""
    from app.services.drug_aliases import expand_aliases, strip_biologic_suffix
    from app.services.drug_assets import _alias_set
    assert strip_biologic_suffix("sacituzumab govitecan-hziy") == "sacituzumab govitecan"
    assert "Trodelvy" in expand_aliases("sacituzumab govitecan-hziy")
    assert _alias_set("sacituzumab govitecan-hziy") & _alias_set("Trodelvy")
    # Three-letter stems are not suffixes: exa-cel must survive intact.
    assert strip_biologic_suffix("exa-cel") == "exa-cel"
    assert "Casgevy" in expand_aliases("exa-cel")


def test_a_filings_own_shorthand_is_expanded_to_the_programme_it_names():
    """Gilead introduces "sacituzumab govitecan-hziy" then refers to it as "SG"."""
    from app.services.drug_assets import canonical_name
    names = ["sacituzumab govitecan-hziy", "SG", "domvanalimab", "dom and zim"]
    assert canonical_name("SG", names) == "sacituzumab govitecan-hziy"
    # A combination is a real programme of its own, not shorthand for either half.
    assert canonical_name("dom and zim", names) == "dom and zim"
    # Full names are never rewritten.
    assert canonical_name("domvanalimab", names) == "domvanalimab"


def test_an_ambiguous_abbreviation_is_left_alone_rather_than_guessed():
    from app.services.drug_assets import canonical_name
    assert canonical_name("SG", ["sacituzumab govitecan", "sotorasib gamma"]) == "SG"


def test_shorthand_is_resolved_before_the_asset_is_keyed():
    filing = business([program("sacituzumab govitecan-hziy", "breast cancer"),
                       program("SG", "lung cancer")])
    assets = build_assets([TRIKAFTA, ALYFTREK], filing, 2026)
    pipeline = [a for a in assets if a["kind"] == "pipeline"]
    # Same molecule, two indications: two assets, but one recognisable name.
    assert {a["name"] for a in pipeline} == {"sacituzumab govitecan-hziy"}
    assert len({a["key"] for a in pipeline}) == 2


def test_duplicate_shorthand_merges_evidence_without_merging_indications():
    filing = business([
        program("AB", "cancer", phase="phase_2", quote="short quote", aliases=["Alias"]),
        program("Alpha Beta", "cancer", phase="filed", quote="full quote"),
        program("Alpha Beta", "other cancer", phase="phase_3"),
    ])
    assets = build_assets([], filing, 2026)
    assert len(assets) == 2
    cancer = next(a for a in assets if a["indication"] == "cancer")
    assert cancer["name"] == "Alpha Beta" and cancer["phase"] == "filed"
    assert cancer["extracted"]["quote"] == "full quote\nshort quote"


def test_already_served_is_excluded_even_without_population_disclosure():
    from app.services.drug_assets import ALREADY_SERVED, CONTINUING_VALUE_ELIGIBLE
    filing = {"marketed": MARKETED, "populations": [],
              "pipeline": [program("New molecule", "CF", phase="filed")]}
    assets = build_assets([TRIKAFTA], filing, 2026)
    pipeline = next(a for a in assets if a["kind"] == "pipeline")
    assert pipeline["extracted"]["unvalued_code"] == ALREADY_SERVED
    assert pipeline["extracted"]["unvalued_code"] not in CONTINUING_VALUE_ELIGIBLE
