"""Tests for XBRL company-facts normalization."""
from __future__ import annotations

import pytest

from app.models.common import MetricStatus
from app.providers.mock_provider import MockSecProvider
from app.services.normalization import normalize_company_facts


def _by_concept(result, concept, fiscal_year):
    return next(
        m for m in result.metrics if m.concept == concept and m.fiscal_year == fiscal_year
    )


def test_mock_company_normalizes_expected_latest_values():
    payload = MockSecProvider().get_company_facts("VALX").payload
    result = normalize_company_facts(payload, source="mock")

    assert result.entity_name.endswith("(SAMPLE)")
    fy = max(m.fiscal_year for m in result.metrics if m.fiscal_year)
    assert fy == 2025

    revenue = _by_concept(result, "revenue", fy)
    assert revenue.value == 1290e6
    assert revenue.status == MetricStatus.REPORTED
    assert revenue.accession_number  # provenance retained
    assert revenue.xbrl_concept == "Revenues"


def test_total_debt_is_derived_from_components():
    payload = MockSecProvider().get_company_facts("VALX").payload
    result = normalize_company_facts(payload, source="mock")
    debt = _by_concept(result, "total_debt", 2025)
    # 460M (noncurrent) + 50M (current) = 510M
    assert debt.value == 510e6
    assert debt.status == MetricStatus.DERIVED
    assert debt.source == "derived"


def test_ebitda_is_derived_from_operating_income_plus_da():
    payload = MockSecProvider().get_company_facts("VALX").payload
    result = normalize_company_facts(payload, source="mock")
    ebitda = _by_concept(result, "ebitda", 2025)
    # OI 95M + D&A 85M = 180M
    assert ebitda.value == 180e6
    assert ebitda.status == MetricStatus.DERIVED


def test_missing_concept_produces_missing_status_and_warning():
    payload = {
        "cik": 123, "entityName": "Empty Co (SAMPLE)",
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                {"val": 100.0, "start": "2024-01-01", "end": "2024-12-31",
                 "fy": 2024, "fp": "FY", "form": "10-K", "accn": "x-24-1"},
            ]}},
        }},
    }
    result = normalize_company_facts(payload, source="mock")
    cash = _by_concept(result, "cash", 2024)
    assert cash.value is None
    assert cash.status == MetricStatus.MISSING
    assert any("cash" in w for w in result.warnings)
    # EBITDA cannot be derived without D&A -> MISSING (honest, not fabricated).
    ebitda = _by_concept(result, "ebitda", 2024)
    assert ebitda.status == MetricStatus.MISSING


def test_negative_cash_flagged_inconsistent():
    payload = {
        "cik": 1, "entityName": "Weird Co (SAMPLE)",
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                {"val": 100.0, "start": "2024-01-01", "end": "2024-12-31",
                 "fy": 2024, "fp": "FY", "form": "10-K", "accn": "a-24-1"}]}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
                {"val": -5.0, "end": "2024-12-31", "fy": 2024, "fp": "FY",
                 "form": "10-K", "accn": "a-24-1"}]}},
        }},
    }
    result = normalize_company_facts(payload, source="mock")
    cash = _by_concept(result, "cash", 2024)
    assert cash.status == MetricStatus.INCONSISTENT
    assert cash.confidence < 1.0


def _flow(val, year, fy, accn):
    return {"val": val, "start": f"{year}-01-01", "end": f"{year}-12-31",
            "fy": fy, "fp": "FY", "form": "10-K", "accn": accn, "filed": f"{fy + 1}-02-15"}


def test_comparative_years_keyed_by_period_not_report_fy():
    """A 10-K tags prior-year comparatives with the report's fy; we must key by period."""
    payload = {
        "cik": 10, "entityName": "Comparatives Co (SAMPLE)",
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            # FY2025 10-K reports 2023/2024/2025, all tagged fy=2025.
            _flow(100.0, 2023, 2025, "r-25"),
            _flow(110.0, 2024, 2025, "r-25"),
            _flow(120.0, 2025, 2025, "r-25"),
            # FY2024 10-K reports 2023/2024, tagged fy=2024.
            _flow(100.0, 2023, 2024, "r-24"),
            _flow(110.0, 2024, 2024, "r-24"),
        ]}}}},
    }
    result = normalize_company_facts(payload, source="sec_edgar")
    revs = [m for m in result.metrics if m.concept == "revenue" and m.value is not None]
    by_year = {m.fiscal_year: m.value for m in revs}
    assert by_year == {2025: 120.0, 2024: 110.0, 2023: 100.0}
    # No duplicate fiscal years for a concept.
    years = [m.fiscal_year for m in revs]
    assert len(years) == len(set(years))
    # Period-end year matches the label.
    for m in revs:
        assert m.period_end.year == m.fiscal_year


def test_tag_switch_is_merged_across_candidates():
    """Filer used RevenueFromContract... for old years, then switched to Revenues."""
    payload = {
        "cik": 11, "entityName": "TagSwitch Co (SAMPLE)",
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                _flow(80.0, 2022, 2022, "a-22"),
            ]}},
            "Revenues": {"units": {"USD": [
                _flow(120.0, 2024, 2024, "b-24"),
            ]}},
        }},
    }
    result = normalize_company_facts(payload, source="sec_edgar")
    by_year = {m.fiscal_year: m for m in result.metrics if m.concept == "revenue" and m.value is not None}
    assert by_year[2024].value == 120.0
    assert by_year[2024].xbrl_concept == "Revenues"
    assert by_year[2022].value == 80.0
    assert by_year[2022].xbrl_concept == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_quarterly_facts_excluded_from_annual_flows():
    """A quarter tagged fp=FY (rare) must not be picked as the annual value."""
    payload = {
        "cik": 12, "entityName": "Quarter Co (SAMPLE)",
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            _flow(400.0, 2024, 2024, "y-24"),
            # A 3-month period mislabeled fp=FY — must be ignored (duration guard).
            {"val": 95.0, "start": "2024-01-01", "end": "2024-03-31", "fy": 2024,
             "fp": "FY", "form": "10-K", "accn": "y-24", "filed": "2025-02-15"},
        ]}}}},
    }
    result = normalize_company_facts(payload, source="sec_edgar")
    rev = _by_concept(result, "revenue", 2024)
    assert rev.value == 400.0


def test_operating_income_derived_when_not_tagged():
    """OperatingIncomeLoss absent → derive from GrossProfit − OperatingExpenses."""
    payload = {
        "cik": 13, "entityName": "DerivedOI Co (SAMPLE)",
        "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [_flow(500.0, 2024, 2024, "d-24")]}},
            "GrossProfit": {"units": {"USD": [_flow(300.0, 2024, 2024, "d-24")]}},
            "OperatingExpenses": {"units": {"USD": [_flow(180.0, 2024, 2024, "d-24")]}},
        }},
    }
    result = normalize_company_facts(payload, source="sec_edgar")
    oi = _by_concept(result, "operating_income", 2024)
    assert oi.value == 120.0  # 300 - 180
    assert oi.status == MetricStatus.DERIVED


def test_revenue_fallback_concept_used_when_primary_absent():
    payload = {
        "cik": 2, "entityName": "Fallback Co (SAMPLE)",
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                {"val": 250.0, "start": "2024-01-01", "end": "2024-12-31",
                 "fy": 2024, "fp": "FY", "form": "10-K", "accn": "b-24-1"}]}},
        }},
    }
    result = normalize_company_facts(payload, source="mock")
    revenue = _by_concept(result, "revenue", 2024)
    assert revenue.value == 250.0
    assert revenue.xbrl_concept == "RevenueFromContractWithCustomerExcludingAssessedTax"


# --- Cash economics (biotech profile inputs) ---------------------------------
def _instant(val, year, fy, accn):
    return {"val": val, "end": f"{year}-12-31", "fy": fy, "fp": "FY", "form": "10-K",
            "accn": accn, "filed": f"{fy + 1}-02-15"}


def _payload(entity, concepts):
    return {"cik": 20, "entityName": entity, "facts": {"us-gaap": {
        name: {"units": {"USD": facts}} for name, facts in concepts.items()}}}


def test_cash_economics_concepts_and_derivations():
    result = normalize_company_facts(MockSecProvider().get_company_facts("VALX").payload, source="mock")
    ocf = _by_concept(result, "operating_cash_flow", 2025)
    assert ocf.value == 140e6 and ocf.status == MetricStatus.REPORTED

    fcf = _by_concept(result, "free_cash_flow", 2025)
    assert fcf.value == 140e6 - 55e6
    assert fcf.status == MetricStatus.DERIVED

    liquidity = _by_concept(result, "liquidity", 2025)
    assert liquidity.value == 1240e6 + 700e6 + 320e6
    assert "marketable securities" in liquidity.quality_note


def test_liquidity_is_cash_only_without_securities_and_raises_no_missing_rows():
    result = normalize_company_facts(MockSecProvider().get_company_facts("CARO").payload, source="mock")
    liquidity = _by_concept(result, "liquidity", 2025)
    assert liquidity.value == 500e6
    assert "Cash and equivalents only" in liquidity.quality_note
    # Holding no securities is not a data gap: no MISSING rows and no warnings.
    assert not [m for m in result.metrics if m.concept.startswith("marketable_securities")]
    assert not any("marketable" in w for w in result.warnings)


def test_long_term_investments_are_not_counted_as_liquidity():
    """Equity stakes are not liquid; only cash and debt/marketable securities count."""
    payload = _payload("Equity Stakes Co (SAMPLE)", {
        "Revenues": [_flow(500.0, 2025, 2025, "e-25")],
        "CashAndCashEquivalentsAtCarryingValue": [_instant(100.0, 2025, 2025, "e-25")],
        "LongTermInvestments": [_instant(900.0, 2025, 2025, "e-25")],
    })
    result = normalize_company_facts(payload, source="sec_edgar")
    assert _by_concept(result, "liquidity", 2025).value == 100.0


def test_rd_tag_switch_merges_per_year_preferring_ipr_d_exclusion():
    """Vertex-style: total R&D tag through 2021, IPR&D-excluding tag from 2020 onward."""
    payload = _payload("R&D Switch Co (SAMPLE)", {
        "Revenues": [_flow(1000.0, y, y, f"r-{y}") for y in (2019, 2020, 2021, 2022)],
        "ResearchAndDevelopmentExpense": [
            _flow(280.0, 2019, 2019, "r-2019"), _flow(300.0, 2020, 2020, "r-2020"),
            _flow(320.0, 2021, 2021, "r-2021")],
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost": [
            _flow(290.0, 2020, 2020, "r-2020"), _flow(310.0, 2021, 2021, "r-2021"),
            _flow(350.0, 2022, 2022, "r-2022")],
    })
    result = normalize_company_facts(payload, source="sec_edgar")
    rd = {m.fiscal_year: m for m in result.metrics
          if m.concept == "research_development" and m.value is not None}
    # Overlap years take the preferred tag; 2019 falls back to the only tag filed.
    assert {y: m.value for y, m in rd.items()} == {2019: 280.0, 2020: 290.0, 2021: 310.0, 2022: 350.0}
    assert rd[2019].xbrl_concept == "ResearchAndDevelopmentExpense"
    assert rd[2022].xbrl_concept == "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"


def test_capex_falls_back_to_other_ppe_tag():
    """Eli Lilly files capex only as PaymentsToAcquireOtherPropertyPlantAndEquipment."""
    payload = _payload("Other PPE Co (SAMPLE)", {
        "Revenues": [_flow(45.0e9, 2025, 2025, "o-25")],
        "NetCashProvidedByUsedInOperatingActivities": [_flow(12.0e9, 2025, 2025, "o-25")],
        "PaymentsToAcquireOtherPropertyPlantAndEquipment": [_flow(5.26e9, 2025, 2025, "o-25")],
    })
    result = normalize_company_facts(payload, source="sec_edgar")
    assert _by_concept(result, "capex", 2025).value == 5.26e9
    fcf = _by_concept(result, "free_cash_flow", 2025)
    assert fcf.value == pytest.approx(12.0e9 - 5.26e9)
    assert fcf.confidence == 1.0


def test_free_cash_flow_flags_missing_capex():
    payload = _payload("No Capex Co (SAMPLE)", {
        "Revenues": [_flow(500.0, 2025, 2025, "c-25")],
        "NetCashProvidedByUsedInOperatingActivities": [_flow(80.0, 2025, 2025, "c-25")],
    })
    fcf = _by_concept(normalize_company_facts(payload, source="sec_edgar"), "free_cash_flow", 2025)
    assert fcf.value == 80.0
    assert fcf.confidence < 1.0
    assert "no capital expenditure" in fcf.quality_note


def test_derived_provenance_fits_the_stored_column():
    """PostgreSQL enforces VARCHAR(128) and SQLite does not, so overflow only fails in production."""
    from app.models import FinancialMetric
    from app.services.normalization import XBRL_CONCEPT_MAX_LENGTH

    assert FinancialMetric.__table__.c.xbrl_concept.type.length == XBRL_CONCEPT_MAX_LENGTH

    payload = _payload("Long Names Co (SAMPLE)", {
        "Revenues": [_flow(500.0, 2025, 2025, "l-25")],
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": [_instant(100.0, 2025, 2025, "l-25")],
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent": [_instant(50.0, 2025, 2025, "l-25")],
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent": [_instant(25.0, 2025, 2025, "l-25")],
    })
    result = normalize_company_facts(payload, source="sec_edgar")
    liquidity = _by_concept(result, "liquidity", 2025)
    assert liquidity.value == 175.0
    assert len(liquidity.xbrl_concept) <= XBRL_CONCEPT_MAX_LENGTH
    # The compacted column keeps the exact component list in the note.
    assert "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent" in liquidity.quality_note
    assert all(m.xbrl_concept is None or len(m.xbrl_concept) <= XBRL_CONCEPT_MAX_LENGTH
               for m in result.metrics)
