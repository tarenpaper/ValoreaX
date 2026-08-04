"""Deterministic, offline mock SEC provider.

Every value here is **fictional sample data**, clearly labelled "(SAMPLE)" in the
entity name and tagged ``source="mock"`` downstream. It exists so the app runs
with zero network access and so tests are reproducible — it is never presented
as real reported data.

The payloads intentionally mirror the SEC Company-Facts JSON schema so the same
normalizer handles mock and live data identically.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import CompanyNotFound, CompanyProfile, RawResponse, SecDataProvider


@dataclass
class _YearFacts:
    """One fiscal year of illustrative annual (10-K) figures, in whole USD / shares."""

    fy: int
    revenue: float
    operating_income: float
    cash: float
    long_term_debt: float
    short_term_debt: float
    depreciation_amortization: float
    shares_outstanding: float
    income_tax_expense: float


@dataclass
class _MockCompany:
    ticker: str
    name: str
    cik: str
    sector: str
    industry: str
    exchange: str
    years: list[_YearFacts]


# --- Fictional sample universe (healthcare) --------------------------------
_UNIVERSE: dict[str, _MockCompany] = {
    "VALX": _MockCompany(
        ticker="VALX",
        name="Valorea Therapeutics, Inc. (SAMPLE)",
        cik="0009000001",
        sector="Healthcare",
        industry="Biotechnology",
        exchange="NASDAQ",
        years=[
            _YearFacts(2023, 820e6, -140e6, 1350e6, 480e6, 40e6, 60e6, 210e6, 5e6),
            _YearFacts(2024, 1020e6, -60e6, 1180e6, 500e6, 45e6, 72e6, 226e6, 8e6),
            _YearFacts(2025, 1290e6, 95e6, 1240e6, 460e6, 50e6, 85e6, 240e6, 18e6),
        ],
    ),
    "HELX": _MockCompany(
        ticker="HELX",
        name="Helix Biopharma Corp. (SAMPLE)",
        cik="0009000002",
        sector="Healthcare",
        industry="Pharmaceuticals",
        exchange="NASDAQ",
        years=[
            _YearFacts(2023, 3400e6, 610e6, 2100e6, 1800e6, 150e6, 240e6, 480e6, 120e6),
            _YearFacts(2024, 3720e6, 720e6, 2450e6, 1650e6, 140e6, 260e6, 486e6, 150e6),
            _YearFacts(2025, 4010e6, 812e6, 2780e6, 1500e6, 130e6, 275e6, 492e6, 175e6),
        ],
    ),
    "CARO": _MockCompany(
        ticker="CARO",
        name="Cardyx Medical Devices, Inc. (SAMPLE)",
        cik="0009000003",
        sector="Healthcare",
        industry="Medical Devices",
        exchange="NYSE",
        years=[
            _YearFacts(2023, 1560e6, 210e6, 340e6, 620e6, 60e6, 95e6, 88e6, 46e6),
            _YearFacts(2024, 1690e6, 245e6, 410e6, 580e6, 55e6, 102e6, 90e6, 54e6),
            _YearFacts(2025, 1840e6, 288e6, 500e6, 540e6, 50e6, 110e6, 92e6, 63e6),
        ],
    ),
}


def _flow_fact(val: float, fy: int, accn: str) -> dict:
    """A duration ('flow') XBRL fact spanning a full fiscal year."""
    return {
        "start": f"{fy}-01-01",
        "end": f"{fy}-12-31",
        "val": val,
        "fy": fy,
        "fp": "FY",
        "form": "10-K",
        "accn": accn,
        "frame": f"CY{fy}",
        "filed": f"{fy + 1}-02-15",
    }


def _instant_fact(val: float, fy: int, accn: str) -> dict:
    """An instantaneous ('balance sheet') XBRL fact at fiscal year end."""
    return {
        "end": f"{fy}-12-31",
        "val": val,
        "fy": fy,
        "fp": "FY",
        "form": "10-K",
        "accn": accn,
        "frame": f"CY{fy}Q4I",
        "filed": f"{fy + 1}-02-15",
    }


def _build_company_facts(company: _MockCompany) -> dict:
    """Assemble a Company-Facts-shaped payload from the sample year rows."""
    usd: dict[str, dict] = {c: {"label": c, "units": {"USD": []}} for c in (
        "Revenues",
        "OperatingIncomeLoss",
        "CashAndCashEquivalentsAtCarryingValue",
        "LongTermDebtNoncurrent",
        "LongTermDebtCurrent",
        "DepreciationDepletionAndAmortization",
        "IncomeTaxExpenseBenefit",
    )}
    shares = {"EntityCommonStockSharesOutstanding": {"label": "Shares Outstanding", "units": {"shares": []}}}

    for y in company.years:
        accn = f"{company.cik[-10:]}-{str(y.fy)[2:]}-000001"
        usd["Revenues"]["units"]["USD"].append(_flow_fact(y.revenue, y.fy, accn))
        usd["OperatingIncomeLoss"]["units"]["USD"].append(_flow_fact(y.operating_income, y.fy, accn))
        usd["DepreciationDepletionAndAmortization"]["units"]["USD"].append(
            _flow_fact(y.depreciation_amortization, y.fy, accn)
        )
        usd["IncomeTaxExpenseBenefit"]["units"]["USD"].append(_flow_fact(y.income_tax_expense, y.fy, accn))
        usd["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"].append(_instant_fact(y.cash, y.fy, accn))
        usd["LongTermDebtNoncurrent"]["units"]["USD"].append(_instant_fact(y.long_term_debt, y.fy, accn))
        usd["LongTermDebtCurrent"]["units"]["USD"].append(_instant_fact(y.short_term_debt, y.fy, accn))
        shares["EntityCommonStockSharesOutstanding"]["units"]["shares"].append(
            _instant_fact(y.shares_outstanding, y.fy, accn)
        )

    return {
        "cik": int(company.cik),
        "entityName": company.name,
        "facts": {"dei": shares, "us-gaap": usd},
    }


class MockSecProvider(SecDataProvider):
    """In-memory provider backed by ``_UNIVERSE``. No network calls."""

    name = "mock"

    def _lookup(self, ticker: str) -> _MockCompany:
        company = _UNIVERSE.get(ticker.upper())
        if company is None:
            raise CompanyNotFound(
                f"Ticker {ticker!r} is not in the mock universe "
                f"({', '.join(_UNIVERSE)}). Set SEC_PROVIDER=sec_edgar for live data."
            )
        return company

    def get_profile(self, ticker: str) -> CompanyProfile:
        c = self._lookup(ticker)
        return CompanyProfile(
            ticker=c.ticker,
            name=c.name,
            cik=c.cik,
            sector=c.sector,
            industry=c.industry,
            exchange=c.exchange,
        )

    def get_company_facts(self, ticker: str) -> RawResponse:
        c = self._lookup(ticker)
        return RawResponse(
            provider=self.name,
            resource_type="company_facts",
            resource_key=c.cik,
            payload=_build_company_facts(c),
        )

    @staticmethod
    def available_tickers() -> list[str]:
        return sorted(_UNIVERSE)
