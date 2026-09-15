"""Plutus extraction of pipeline, populations and exclusivity from 10-K text.

Fixtures reproduce real FY2025 filing text, including the flattened tables where footnote
markers sit between values ("KALYDECO 2028 1 2027 2,3").
"""
from __future__ import annotations

import json

import pytest

from app.providers.base import ProviderError
from app.services.llm_filing import (
    EXCLUSIVITY_BUDGET,
    as_evidence,
    effective_loe,
    html_to_text,
    normalize_phase,
    select_exclusivity_passages,
    validate_business,
    validate_exclusivity,
)

# Vertex's exclusivity table, as it appears once tags are stripped.
VERTEX_TABLE = (
    "Unless otherwise noted, patent term extensions, and pediatric exclusivity periods are not "
    "reflected in the expiration dates listed in the table below and may extend protection. "
    "Product Expiration Year of U.S. Basic Product Patent Expiration Year of European Basic "
    "Product Patent KALYDECO 2028 1 2027 2,3 ORKAMBI 2031 1 2030 2 SYMDEKO/SYMKEVI 2027 2033 2 "
    "TRIKAFTA/KAFTRIO 2037 2037 CASGEVY 2035 4 2034 5,6 ALYFTREK 2039 2039 JOURNAVX 2040 2040 "
    "1 Includes pediatric exclusivity."
)
# Lilly lists several protections per product; the later one is what matters.
LILLY_TABLE = (
    "The relevant patent protection or data protection and associated expiry dates for our major "
    "marketed products are as follows: Therapeutic Area Product Protection Territory Estimated "
    "Expiry Date Cardiometabolic Health products Mounjaro/ Zepbound compound patent U.S. 2036 "
    "major European countries 2037 Japan 2040 data protection U.S. 2027 major European countries 2033"
)
VERTEX_BUSINESS = (
    "We are developing povetacicept, a dual inhibitor of the BAFF and APRIL pathways, for IgA "
    "nephropathy, and completed enrollment in the povetacicept Phase 3 clinical trial. There are "
    "approximately 112,000 people with CF in all target markets. TRIKAFTA/KAFTRIO is approved "
    "for cystic fibrosis."
)


def evidence_for(text, label="10-K excerpt"):
    return as_evidence(text, label)


def raw(payload):
    return json.dumps(payload)


# --- Text and passage selection ---------------------------------------------------
def test_html_to_text_strips_markup_and_collapses_space():
    text = html_to_text("<div><style>p{color:red}</style><p>Trikafta&nbsp;2037</p>\n\n<p>and more</p></div>")
    assert text == "Trikafta 2037 and more"
    assert "color:red" not in text


def test_exclusivity_selection_finds_the_patent_table_not_other_year_tables():
    """Scoring on years alone lands on debt maturity tables; wording must anchor it."""
    debt_table = "Debt maturities: 2026 400 2027 600 2028 900 2029 250 2030 175 " * 40
    document = f"{debt_table} ... {VERTEX_TABLE} ... {debt_table}"
    passage = select_exclusivity_passages(document, EXCLUSIVITY_BUDGET)
    assert "TRIKAFTA/KAFTRIO 2037 2037" in passage
    assert "JOURNAVX 2040 2040" in passage


def test_evidence_chunks_overlap_so_quotes_do_not_straddle_boundaries():
    chunks = as_evidence("x" * 4_000, "excerpt")
    assert [c["id"] for c in chunks] == ["E1", "E2", "E3"]
    assert sum(len(c["text"]) for c in chunks) > 4_000  # overlap repeats some text


# --- Exclusivity ------------------------------------------------------------------
def test_short_table_quotes_are_accepted_when_product_and_year_are_present():
    evidence = evidence_for(VERTEX_TABLE)
    rows = [{"product": "TRIKAFTA/KAFTRIO", "protection": "compound_patent", "territory": "us",
             "expiry_year": 2037, "evidence_id": "E1", "quote": "TRIKAFTA/KAFTRIO 2037"},
            {"product": "JOURNAVX", "protection": "compound_patent", "territory": "us",
             "expiry_year": 2040, "evidence_id": "E1", "quote": "JOURNAVX 2040 2040"}]
    kept = validate_exclusivity(raw({"rows": rows, "caveats": []}), evidence)
    assert len(kept["rows"]) == 2
    assert {r["expiry_year"] for r in kept["rows"]} == {2037, 2040}


def test_exclusivity_rejects_fabricated_altered_and_malformed_rows():
    evidence = evidence_for(VERTEX_TABLE)
    good = {"product": "ALYFTREK", "protection": "compound_patent", "territory": "us",
            "expiry_year": 2039, "evidence_id": "E1", "quote": "ALYFTREK 2039 2039"}
    cases = [
        {**good, "quote": "ALYFTREK 2045 2045"},                      # quote not in the filing
        {**good, "expiry_year": 2045},                                 # year absent from its quote
        {**good, "product": "INVENTED"},                               # product absent from quote
        {**good, "territory": "mars"},                                 # not an allowed territory
        {**good, "protection": "vibes"},                               # not an allowed protection
        {**good, "expiry_year": 1789},                                 # implausible year
        {**good, "evidence_id": "E9"},                                 # cites a chunk that does not exist
    ]
    for bad in cases:
        kept = validate_exclusivity(raw({"rows": [bad], "caveats": []}), evidence)
        assert kept["rows"] == [], bad
    assert len(validate_exclusivity(raw({"rows": [good], "caveats": []}), evidence)["rows"]) == 1


def test_effective_loe_takes_the_latest_protection_per_territory():
    """Mounjaro's US compound patent runs to 2036; its US data protection ends 2027."""
    evidence = evidence_for(LILLY_TABLE)
    rows = [{"product": "Mounjaro/ Zepbound", "protection": "compound_patent", "territory": "us",
             "expiry_year": 2036, "evidence_id": "E1", "quote": "Mounjaro/ Zepbound compound patent U.S. 2036"},
            {"product": "Mounjaro/ Zepbound", "protection": "data_protection", "territory": "us",
             "expiry_year": 2027, "evidence_id": "E1", "quote": "data protection U.S. 2027"}]
    kept = validate_exclusivity(raw({"rows": rows, "caveats": []}), evidence)
    # The data-protection row quotes the table but not the product name, so only one verifies.
    verified = kept["rows"]
    assert verified and all(r["territory"] == "us" for r in verified)
    assert effective_loe(rows)["us"]["expiry_year"] == 2036
    assert effective_loe(list(reversed(rows)))["us"]["expiry_year"] == 2036


def test_caveats_are_kept_with_their_quote():
    evidence = evidence_for(VERTEX_TABLE)
    caveat = {"text": "Patent term extensions and pediatric exclusivity are not reflected.",
              "evidence_id": "E1",
              "quote": "patent term extensions, and pediatric exclusivity periods are not reflected"}
    kept = validate_exclusivity(raw({"rows": [], "caveats": [caveat]}), evidence)
    assert len(kept["caveats"]) == 1
    fabricated = {**caveat, "quote": "dates already include every possible extension"}
    assert validate_exclusivity(raw({"rows": [], "caveats": [fabricated]}), evidence)["caveats"] == []


def test_malformed_response_raises_provider_error():
    for bad in ("not json", "null", "[]"):
        with pytest.raises(ProviderError):
            validate_exclusivity(bad, evidence_for(VERTEX_TABLE))


# --- Business ---------------------------------------------------------------------
def test_pipeline_populations_and_products_require_supporting_quotes():
    evidence = evidence_for(VERTEX_BUSINESS)
    payload = {
        "pipeline": [{"name": "povetacicept", "aliases": [], "indication": "IgA nephropathy",
                      "phase": "phase_3", "milestone": "completed enrollment", "evidence_id": "E1",
                      "quote": "completed enrollment in the povetacicept Phase 3 clinical trial"}],
        "marketed": [{"name": "TRIKAFTA/KAFTRIO", "indication": "cystic fibrosis", "evidence_id": "E1",
                      "quote": "TRIKAFTA/KAFTRIO is approved for cystic fibrosis."}],
        "populations": [{"indication": "CF", "patients": 112000, "geography": "worldwide",
                         "evidence_id": "E1",
                         "quote": "There are approximately 112,000 people with CF in all target markets."}],
    }
    kept = validate_business(raw(payload), evidence)
    assert kept["pipeline"][0]["phase"] == "phase_3"
    assert kept["marketed"][0]["name"] == "TRIKAFTA/KAFTRIO"
    assert kept["populations"][0]["patients"] == 112000


def test_business_drops_unsupported_items():
    evidence = evidence_for(VERTEX_BUSINESS)
    base = {"pipeline": [], "marketed": [], "populations": []}

    # A population number that does not appear in its quote is invented.
    inflated = {**base, "populations": [{"indication": "CF", "patients": 500000, "geography": "worldwide",
                                         "evidence_id": "E1",
                                         "quote": "There are approximately 112,000 people with CF in all target markets."}]}
    assert validate_business(raw(inflated), evidence)["populations"] == []

    # An unsupported geography enum, and a programme whose quote is not in the filing.
    bad_geo = {**base, "populations": [{"indication": "CF", "patients": 112000, "geography": "moon",
                                        "evidence_id": "E1", "quote": "approximately 112,000 people with CF"}]}
    assert validate_business(raw(bad_geo), evidence)["populations"] == []

    fabricated = {**base, "pipeline": [{"name": "madeupstat", "indication": "x", "phase": "phase_3",
                                        "evidence_id": "E1", "quote": "madeupstat entered Phase 3 last year."}]}
    assert validate_business(raw(fabricated), evidence)["pipeline"] == []

    # A real sentence that never names the drug cannot support a claim about it.
    unnamed = {**base, "pipeline": [{"name": "povetacicept", "indication": "IgAN", "phase": "phase_3",
                                     "evidence_id": "E1",
                                     "quote": "There are approximately 112,000 people with CF in all target markets."}]}
    assert validate_business(raw(unnamed), evidence)["pipeline"] == []


def test_phase_normalization_prefers_the_more_specific_label():
    assert normalize_phase("Phase 2/3 study") == "phase_2_3"
    assert normalize_phase("a Phase 1/2 trial") == "phase_1_2"
    assert normalize_phase("Phase 3") == "phase_3"
    assert normalize_phase("preclinical work") == "preclinical"
    assert normalize_phase("no stage mentioned") is None


def test_phase_is_recovered_from_the_quote_when_the_field_is_unusable():
    evidence = evidence_for(VERTEX_BUSINESS)
    payload = {"pipeline": [{"name": "povetacicept", "indication": "IgAN", "phase": "late stage",
                             "evidence_id": "E1",
                             "quote": "completed enrollment in the povetacicept Phase 3 clinical trial"}],
               "marketed": [], "populations": []}
    assert validate_business(raw(payload), evidence)["pipeline"][0]["phase"] == "phase_3"
