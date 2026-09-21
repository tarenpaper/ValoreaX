"""Normalize a Company-Facts payload into our concept vocabulary.

Responsibilities:
  * map raw XBRL concepts (with sensible fallbacks) to normalized concepts
  * select annual (fiscal-year) values and de-duplicate restatements
  * derive EBITDA, total debt, free cash flow and liquidity where the components exist
  * attach full provenance + a data-quality status to every value
  * surface human-readable warnings for missing/inconsistent inputs

Flatten/group/select is plain Python. The output is dataclasses so the
persistence and API layers stay free of dataframe libraries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.common import MetricStatus

# Normalized concept -> ordered list of (taxonomy, xbrl_concept) candidates.
# Earlier candidates win when present.
CONCEPT_MAP: dict[str, list[tuple[str, str]]] = {
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
        ("us-gaap", "SalesRevenueNet"),
    ],
    "operating_income": [("us-gaap", "OperatingIncomeLoss")],
    # Fallback components to derive operating income when it isn't tagged directly.
    "gross_profit": [("us-gaap", "GrossProfit")],
    "operating_expenses": [("us-gaap", "OperatingExpenses")],
    "costs_and_expenses": [("us-gaap", "CostsAndExpenses")],
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    ],
    "depreciation_amortization": [
        ("us-gaap", "DepreciationDepletionAndAmortization"),
        ("us-gaap", "DepreciationAmortizationAndAccretionNet"),
        ("us-gaap", "DepreciationAndAmortization"),
    ],
    "income_tax_expense": [("us-gaap", "IncomeTaxExpenseBenefit")],
    "debt_noncurrent": [
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "LongTermDebt"),
    ],
    "debt_current": [
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "DebtCurrent"),
        ("us-gaap", "ShortTermBorrowings"),
    ],
    "shares_outstanding": [
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
    ],
    # --- Biotech cash economics (see app/services/biotech_profile.py) -----------
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    ],
    # Eli Lilly files total capex under the "Other" PP&E tag, so it is a real fallback.
    # When a filer reports both, the total tag wins per year (see _pick_concept).
    "capex": [
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireOtherPropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireProductiveAssets"),
    ],
    # Debt/marketable securities only. `LongTermInvestments` is deliberately absent: it
    # includes equity stakes that are not liquid. Combined cash-plus-investments totals
    # are also absent, since adding them to cash would double count.
    "marketable_securities_current": [
        ("us-gaap", "MarketableSecuritiesCurrent"),
        ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
        ("us-gaap", "ShortTermInvestments"),
    ],
    "marketable_securities_noncurrent": [
        ("us-gaap", "MarketableSecuritiesNoncurrent"),
        ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"),
    ],
    # The acquired-IPR&D-excluding tag goes first: it is what filers switched to (Vertex
    # from 2020), and it keeps lumpy in-licensing charges out of R&D intensity.
    "research_development": [
        ("us-gaap", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"),
        ("us-gaap", "ResearchAndDevelopmentExpense"),
    ],
    "sga": [
        ("us-gaap", "SellingGeneralAndAdministrativeExpense"),
        ("us-gaap", "GeneralAndAdministrativeExpense"),
    ],
    # --- rNPV cost structure (see app/services/rnpv.py) --------------------------
    "cost_of_revenue": [
        ("us-gaap", "CostOfGoodsAndServicesSold"),
        ("us-gaap", "CostOfRevenue"),
        ("us-gaap", "CostOfGoodsSold"),
    ],
    "interest_expense": [("us-gaap", "InterestExpense"), ("us-gaap", "InterestAndDebtExpense")],
    # Consolidated pretax income only. The Domestic and Foreign variants are partial and
    # deliberately excluded, since they would understate the effective tax base.
    "pretax_income": [
        ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
        ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
    ],
}

# Concepts surfaced to the dashboard as first-class financial inputs.
PRIMARY_CONCEPTS = ["revenue", "operating_income", "ebitda", "cash", "total_debt", "shares_outstanding"]

_FLOW_CONCEPTS = {
    "revenue", "operating_income", "depreciation_amortization", "income_tax_expense",
    "gross_profit", "operating_expenses", "costs_and_expenses",
    "operating_cash_flow", "capex", "research_development", "sga",
    "cost_of_revenue", "pretax_income", "interest_expense",
}
# Must match `FinancialMetric.xbrl_concept` (tests/test_normalization.py asserts this).
XBRL_CONCEPT_MAX_LENGTH = 128

# Liquid securities summed into liquidity. Kept separate from _OPTIONAL_CONCEPTS so that
# adding an optional concept can never leak into the liquidity total.
_SECURITIES_CONCEPTS = ("marketable_securities_current", "marketable_securities_noncurrent")
# Reported only when present. Many companies hold no marketable securities, and a
# pre-revenue company has no cost of goods and no income tax expense, so absence is not a
# data-quality gap and must not raise a MISSING row or warning.
_OPTIONAL_CONCEPTS = (*_SECURITIES_CONCEPTS, "cost_of_revenue", "pretax_income", "interest_expense",
                      "income_tax_expense")
# Concepts keyed by report fiscal year (`fy`) rather than period-end year. DEI
# cover-page shares are dated at the filing date, not the fiscal year end.
_YEAR_FROM_FY = {"shares_outstanding"}
_UNIT_BY_CONCEPT = {"shares_outstanding": "shares"}
_ANNUAL_MIN_DAYS = 300
_ANNUAL_MAX_DAYS = 400


@dataclass
class FilingDescriptor:
    accession_number: str
    form: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    period_end: date | None
    filed_date: date | None


@dataclass
class NormalizedMetric:
    concept: str
    value: float | None
    unit: str
    fiscal_year: int | None
    fiscal_period: str | None
    period_start: date | None
    period_end: date | None
    xbrl_concept: str | None
    taxonomy: str | None
    form: str | None
    accession_number: str | None
    source: str
    status: MetricStatus
    confidence: float
    quality_note: str | None = None


@dataclass
class NormalizationResult:
    entity_name: str
    cik: str | None
    metrics: list[NormalizedMetric]
    filings: dict[str, FilingDescriptor]
    warnings: list[str] = field(default_factory=list)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


_ANNUAL_FRAME = re.compile(r"^CY\d{4}(Q4I)?$")


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and value != value:  # NaN
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _facts_to_rows(payload: dict) -> list[dict]:
    """Flatten a company-facts payload into individual fact dicts."""
    rows: list[dict] = []
    facts = payload.get("facts", {})
    for taxonomy, concepts in facts.items():
        for concept, body in concepts.items():
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    rows.append(
                        {
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "val": e.get("val"),
                            "start": e.get("start"),
                            "end": e.get("end"),
                            "fy": e.get("fy"),
                            "fp": e.get("fp"),
                            "form": e.get("form"),
                            "accn": e.get("accn"),
                            "frame": e.get("frame"),
                            "filed": e.get("filed"),
                        }
                    )
    return rows


def _period_year(row: dict, year_from: str) -> int | None:
    """Fiscal year a fact belongs to.

    Crucially NOT the raw ``fy`` field for most concepts: a 10-K tags its prior-year
    comparatives with the *report's* ``fy``, so we key by the period-end year instead.
    DEI cover-page concepts (shares) are the exception — their ``end`` is the filing
    date, so we honor ``fy`` there.
    """
    if year_from == "fy":
        return _int_or_none(row.get("fy"))
    end = row.get("end")
    if end:
        try:
            return int(str(end)[:4])
        except (ValueError, TypeError):
            return None
    return _int_or_none(row.get("fy"))


def _is_annual_duration(row: dict) -> bool:
    """True when a flow fact spans roughly one year (excludes quarters / YTD stubs)."""
    start, end = row.get("start"), row.get("end")
    if not start or not end:
        return False
    sd, ed = _parse_date(start), _parse_date(end)
    if sd is None or ed is None:
        return False
    return _ANNUAL_MIN_DAYS <= (ed - sd).days <= _ANNUAL_MAX_DAYS


def _annual_by_year(rows: list[dict], taxonomy: str, concept: str, *,
                    is_flow: bool, year_from: str) -> dict[int, dict]:
    """Return {period_year: fact_row} for annual facts of one XBRL concept.

    De-duplicates restatements/comparatives by keeping the most recently *filed*
    value for each period year.
    """
    sub = [r for r in rows if r["taxonomy"] == taxonomy and r["concept"] == concept]
    if not sub:
        return {}
    annual = [r for r in sub if r.get("fp") == "FY"]
    if not annual:
        # Fallback: canonical annual frames like "CY2024" / "CY2024Q4I".
        annual = [r for r in sub if _ANNUAL_FRAME.fullmatch(str(r.get("frame") or ""))]
    if not annual:
        return {}

    if is_flow:
        annual = [r for r in annual if _is_annual_duration(r)]
    # Sort by filed date so later filings overwrite earlier (restatement-aware).
    annual.sort(key=lambda r: str(r.get("filed") or ""))
    picked: dict[int, dict] = {}
    for r in annual:
        py = _period_year(r, year_from)
        if py is not None:
            picked[py] = r
    return picked


def _pick_concept(rows: list[dict], norm_concept: str, candidates: list[tuple[str, str]],
                  ) -> tuple[str | None, str | None, dict[int, dict]]:
    """Merge candidate concepts per-year, highest priority filling each year first.

    Filers switch XBRL tags over time (e.g. Pfizer moved from
    RevenueFromContractWithCustomer... to Revenues). Picking a single concept would
    drop the years the other tag covers, so we merge: for each year, the first
    candidate (in priority order) that has a value for that year wins. Each retained
    row keeps its own concept name, so per-value provenance stays exact.
    """
    is_flow = norm_concept in _FLOW_CONCEPTS
    year_from = "fy" if norm_concept in _YEAR_FROM_FY else "end"
    merged: dict[int, dict] = {}
    for taxonomy, concept in candidates:
        series = _annual_by_year(rows, taxonomy, concept, is_flow=is_flow, year_from=year_from)
        for year, row in series.items():
            merged.setdefault(year, row)  # earlier (higher-priority) candidate wins
    if not merged:
        return None, None, {}
    # Report the concept that covers the most recent year (most relevant for labels).
    latest_year = max(merged)
    return merged[latest_year].get("taxonomy"), merged[latest_year].get("concept"), merged


def _missing_metric(concept: str, fy: int, source: str) -> NormalizedMetric:
    return NormalizedMetric(
        concept=concept, value=None, unit=_UNIT_BY_CONCEPT.get(concept, "USD"),
        fiscal_year=fy, fiscal_period="FY", period_start=None, period_end=None,
        xbrl_concept=None, taxonomy=None, form=None, accession_number=None,
        source=source, status=MetricStatus.MISSING, confidence=0.0,
        quality_note="Concept not reported in the source filing.",
    )


def _operating_income_by_year(resolved: dict[str, dict[int, dict]]) -> dict[int, dict]:
    """Reported-or-derived operating income per year.

    Precedence: reported OperatingIncomeLoss → GrossProfit − OperatingExpenses →
    Revenues − CostsAndExpenses. Each entry keeps a source row for provenance.
    """
    oi = resolved.get("operating_income", {})
    gp = resolved.get("gross_profit", {})
    opex = resolved.get("operating_expenses", {})
    rev = resolved.get("revenue", {})
    costs = resolved.get("costs_and_expenses", {})

    years = set(oi) | (set(gp) & set(opex)) | (set(rev) & set(costs))
    out: dict[int, dict] = {}
    for y in years:
        if y in oi:
            out[y] = {"value": oi[y]["val"], "status": MetricStatus.REPORTED,
                      "xbrl": "OperatingIncomeLoss", "row": oi[y], "note": None}
        elif y in gp and y in opex:
            out[y] = {"value": gp[y]["val"] - opex[y]["val"], "status": MetricStatus.DERIVED,
                      "xbrl": "GrossProfit - OperatingExpenses", "row": gp[y],
                      "note": "Operating income derived as GrossProfit − OperatingExpenses."}
        elif y in rev and y in costs:
            out[y] = {"value": rev[y]["val"] - costs[y]["val"], "status": MetricStatus.DERIVED,
                      "xbrl": "Revenues - CostsAndExpenses", "row": rev[y],
                      "note": "Operating income derived as Revenues − CostsAndExpenses."}
    return out


def _metric_from_row(concept: str, row: dict, source: str, fiscal_year: int,
                     status: MetricStatus = MetricStatus.REPORTED,
                     confidence: float = 1.0, note: str | None = None) -> NormalizedMetric:
    """Build a NormalizedMetric from a picked XBRL fact row.

    ``fiscal_year`` is the period year we keyed on (NOT ``row['fy']``, which is the
    report year and mislabels prior-year comparatives).
    """
    return NormalizedMetric(
        concept=concept,
        value=float(row["val"]) if row.get("val") is not None else None,
        unit=_UNIT_BY_CONCEPT.get(concept, row.get("unit", "USD")),
        fiscal_year=fiscal_year,
        fiscal_period=row.get("fp"),
        period_start=_parse_date(row.get("start")),
        period_end=_parse_date(row.get("end")),
        xbrl_concept=row.get("concept"),
        taxonomy=row.get("taxonomy"),
        form=row.get("form"),
        accession_number=row.get("accn"),
        source=source,
        status=status,
        confidence=confidence,
        quality_note=note,
    )


def _provenance(rows: list[dict], note: str) -> tuple[str | None, str]:
    """Joined XBRL concepts for a derived value, kept within the stored column length.

    PostgreSQL enforces `financial_metrics.xbrl_concept` (VARCHAR(128)); SQLite does not,
    so an over-long join would only fail in production. When the join does not fit, the
    column holds a compact form and the note carries the exact list. Each component is
    also stored as its own row, so no provenance is lost.
    """
    names = [r["concept"] for r in rows if r.get("concept")]
    joined = " + ".join(names)
    if len(joined) <= XBRL_CONCEPT_MAX_LENGTH:
        return joined or None, note
    compact = f"{names[0]} + {len(names) - 1} more"[:XBRL_CONCEPT_MAX_LENGTH]
    return compact, f"{note} Components: {'; '.join(names)}."


def _derived_metric(concept: str, fy: int, value: float | None, rows: list[dict],
                    note: str, confidence: float = 1.0) -> NormalizedMetric:
    """A DERIVED (or MISSING, when `value` is None) metric built from source fact rows.

    Provenance uses each row's own XBRL concept, so a tag switch in one component is
    visible on the derived value rather than hidden behind the latest-year tag.
    """
    anchor = rows[0] if rows else {}
    xbrl_concept, note = _provenance(rows, note)
    return NormalizedMetric(
        concept=concept, value=value, unit="USD", fiscal_year=fy, fiscal_period="FY",
        period_start=_parse_date(anchor.get("start")), period_end=_parse_date(anchor.get("end")),
        xbrl_concept=xbrl_concept,
        taxonomy="derived", form=anchor.get("form"), accession_number=anchor.get("accn"),
        source="derived",
        status=MetricStatus.DERIVED if value is not None else MetricStatus.MISSING,
        confidence=confidence if value is not None else 0.0, quality_note=note,
    )


def _free_cash_flow(resolved: dict[str, dict[int, dict]], fy: int) -> NormalizedMetric:
    """Free cash flow = operating cash flow − capital expenditure."""
    ocf = resolved.get("operating_cash_flow", {}).get(fy)
    capex = resolved.get("capex", {}).get(fy)
    if ocf is None:
        return _derived_metric("free_cash_flow", fy, None, [],
                               "Cannot derive free cash flow: operating cash flow not reported.")
    if capex is None:
        return _derived_metric("free_cash_flow", fy, ocf["val"], [ocf],
                               "Operating cash flow with no capital expenditure reported "
                               "(treated as 0); free cash flow may be overstated.", confidence=0.8)
    return _derived_metric("free_cash_flow", fy, ocf["val"] - capex["val"], [ocf, capex],
                           "Free cash flow = operating cash flow − capital expenditure.")


def _liquidity(resolved: dict[str, dict[int, dict]], fy: int) -> NormalizedMetric:
    """Liquidity = cash and equivalents + current and non-current marketable securities.

    Biotechs hold most of their funding in marketable securities, often long-dated, so
    cash alone badly understates the money available to fund operations.
    """
    cash = resolved.get("cash", {}).get(fy)
    if cash is None:
        return _derived_metric("liquidity", fy, None, [],
                               "Cannot derive liquidity: cash not reported.")
    securities = [row for row in (resolved.get(c, {}).get(fy) for c in _SECURITIES_CONCEPTS) if row]
    note = ("Cash and equivalents + marketable securities (current and non-current where reported)."
            if securities else "Cash and equivalents only; no marketable securities reported.")
    rows = [cash, *securities]
    return _derived_metric("liquidity", fy, sum(r["val"] for r in rows), rows, note)


def normalize_company_facts(payload: dict, source: str, max_years: int = 4) -> NormalizationResult:
    """Convert a raw company-facts payload into normalized metrics + filings."""
    facts = _facts_to_rows(payload)
    entity_name = payload.get("entityName", "")
    cik_raw = payload.get("cik")
    cik = f"{int(cik_raw):010d}" if isinstance(cik_raw, int) else (str(cik_raw) if cik_raw else None)

    warnings: list[str] = []
    metrics: list[NormalizedMetric] = []
    filings: dict[str, FilingDescriptor] = {}

    # Resolve each mapped concept to a per-year series.
    resolved: dict[str, dict[int, dict]] = {}
    used_concept: dict[str, str | None] = {}
    for norm_concept, candidates in CONCEPT_MAP.items():
        taxonomy, xbrl_concept, series = _pick_concept(facts, norm_concept, candidates)
        resolved[norm_concept] = series
        used_concept[norm_concept] = xbrl_concept
        if not series and norm_concept in ("revenue", "cash", "shares_outstanding"):
            warnings.append(f"No data found for '{norm_concept}' (tried {[c for _, c in candidates]}).")

    # Derive operating income per year (reported → GP-OpEx → Rev-Costs), so EBITDA
    # and the operating-income metric survive filers that omit OperatingIncomeLoss.
    oi_by_year = _operating_income_by_year(resolved)
    if not oi_by_year:
        warnings.append("Operating income not reported and not derivable from tagged components.")

    # Determine which fiscal years we have data for, keep the most recent N.
    # Helper-only concepts (GP/OpEx/Costs) don't drive year selection on their own.
    year_driving = ("revenue", "cash", "shares_outstanding", "debt_noncurrent",
                    "debt_current", "depreciation_amortization")
    candidate_years = {fy for c in year_driving for fy in resolved.get(c, {})}
    candidate_years |= set(oi_by_year)
    all_years = sorted(candidate_years, reverse=True)[:max_years]

    for fy in all_years:
        # Register a filing per fiscal year (keyed by the revenue/OI accession if present).
        anchor = None
        for c in ("revenue", "operating_income", "cash", "shares_outstanding"):
            if fy in resolved.get(c, {}):
                anchor = resolved[c][fy]
                break
        if anchor is not None:
            accn = anchor.get("accn")
            if accn and accn not in filings:
                filings[accn] = FilingDescriptor(
                    accession_number=accn,
                    form=anchor.get("form"),
                    fiscal_year=fy,
                    fiscal_period="FY",
                    period_end=_parse_date(anchor.get("end")),
                    filed_date=_parse_date(anchor.get("filed")),
                )

        # Direct (reported) concepts.
        for norm_concept in ("revenue", "cash", "shares_outstanding", "operating_cash_flow",
                             "capex", "research_development", "sga"):
            series = resolved.get(norm_concept, {})
            if fy in series:
                m = _metric_from_row(norm_concept, series[fy], source, fiscal_year=fy)
                if m.value is not None and norm_concept == "cash" and m.value < 0:
                    m.status = MetricStatus.INCONSISTENT
                    m.confidence = 0.5
                    m.quality_note = "Reported cash is negative — verify against the filing."
                    warnings.append(f"FY{fy}: cash value is negative.")
                metrics.append(m)
            else:
                metrics.append(_missing_metric(norm_concept, fy, source))
        for norm_concept in _OPTIONAL_CONCEPTS:
            row = resolved.get(norm_concept, {}).get(fy)
            if row is not None:
                metrics.append(_metric_from_row(norm_concept, row, source, fiscal_year=fy))

        # Operating income (reported or derived from components).
        oi_entry = oi_by_year.get(fy)
        if oi_entry is not None:
            row = oi_entry["row"]
            metrics.append(
                NormalizedMetric(
                    concept="operating_income", value=oi_entry["value"], unit="USD",
                    fiscal_year=fy, fiscal_period="FY",
                    period_start=_parse_date(row.get("start")), period_end=_parse_date(row.get("end")),
                    xbrl_concept=oi_entry["xbrl"],
                    taxonomy="derived" if oi_entry["status"] == MetricStatus.DERIVED else row.get("taxonomy"),
                    form=row.get("form"), accession_number=row.get("accn"),
                    source="derived" if oi_entry["status"] == MetricStatus.DERIVED else source,
                    status=oi_entry["status"],
                    confidence=1.0 if oi_entry["status"] == MetricStatus.REPORTED else 0.85,
                    quality_note=oi_entry["note"],
                )
            )
        else:
            metrics.append(_missing_metric("operating_income", fy, source))

        # --- Derived: total debt = noncurrent + current portion ---
        nc = resolved.get("debt_noncurrent", {}).get(fy)
        cur = resolved.get("debt_current", {}).get(fy)
        total_debt = None
        note = None
        status = MetricStatus.DERIVED
        confidence = 1.0
        if nc is not None or cur is not None:
            total_debt = (nc["val"] if nc else 0.0) + (cur["val"] if cur else 0.0)
            parts = []
            if nc:
                parts.append(f"{nc['concept']}")
            if cur:
                parts.append(f"{cur['concept']}")
            note = "Sum of " + " + ".join(parts) + "."
            if cur is None:
                confidence = 0.8
                note += " Current portion not found; total debt may be understated."
            accn = (nc or cur).get("accn")
            form = (nc or cur).get("form")
        else:
            status = MetricStatus.MISSING
            confidence = 0.0
            note = "No debt concepts reported (treated as ~0 for net-debt calc)."
            accn = None
            form = None
        metrics.append(
            NormalizedMetric(
                concept="total_debt", value=total_debt, unit="USD",
                fiscal_year=fy, fiscal_period="FY", period_start=None,
                period_end=_parse_date((nc or cur or {}).get("end")) if (nc or cur) else None,
                xbrl_concept="+".join(p for p in (
                    used_concept.get("debt_noncurrent"), used_concept.get("debt_current")) if p) or None,
                taxonomy="derived", form=form, accession_number=accn,
                source="derived", status=status, confidence=confidence, quality_note=note,
            )
        )

        # --- Derived: EBITDA = operating income (reported/derived) + D&A ---
        oi_entry = oi_by_year.get(fy)
        da = resolved.get("depreciation_amortization", {}).get(fy)
        if oi_entry is not None and da is not None:
            row = oi_entry["row"]
            ebitda = oi_entry["value"] + da["val"]
            oi_label = "OperatingIncome" if oi_entry["status"] == MetricStatus.REPORTED else "OperatingIncome(derived)"
            metrics.append(
                NormalizedMetric(
                    concept="ebitda", value=ebitda, unit="USD",
                    fiscal_year=fy, fiscal_period="FY",
                    period_start=_parse_date(row.get("start")), period_end=_parse_date(row.get("end")),
                    xbrl_concept=f"{oi_label} + {used_concept.get('depreciation_amortization')}",
                    taxonomy="derived", form=row.get("form"), accession_number=row.get("accn"),
                    source="derived", status=MetricStatus.DERIVED, confidence=1.0,
                    quality_note="EBITDA = operating income + D&A (from reported facts).",
                )
            )
        else:
            missing = "operating income" if oi_entry is None else "D&A"
            metrics.append(
                NormalizedMetric(
                    concept="ebitda", value=None, unit="USD",
                    fiscal_year=fy, fiscal_period="FY", period_start=None, period_end=None,
                    xbrl_concept=None, taxonomy="derived", form=None, accession_number=None,
                    source="derived", status=MetricStatus.MISSING, confidence=0.0,
                    quality_note=f"Cannot derive EBITDA: {missing} not reported.",
                )
            )

        metrics.append(_free_cash_flow(resolved, fy))
        metrics.append(_liquidity(resolved, fy))

    return NormalizationResult(
        entity_name=entity_name, cik=cik, metrics=metrics, filings=filings, warnings=warnings
    )
