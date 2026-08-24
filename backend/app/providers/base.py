"""Provider interfaces and transport dataclasses.

Design goal: make data sources swappable. The mock and the live SEC adapter both
emit the *same* Company-Facts-shaped payload, so a single normalizer
(`app.services.normalization`) works regardless of which provider produced it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


class ProviderError(RuntimeError):
    """Generic provider failure (network, parse, etc.)."""


class CompanyNotFound(ProviderError):
    """Raised when a ticker/CIK cannot be resolved by the provider."""


@dataclass
class CompanyProfile:
    """Lightweight company identity + classification."""

    ticker: str
    name: str
    cik: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    currency: str = "USD"


@dataclass
class RawResponse:
    """An unmodified provider payload, ready to be persisted as raw."""

    provider: str
    resource_type: str          # e.g. "company_facts"
    resource_key: str           # e.g. a CIK
    payload: dict               # parsed JSON, stored verbatim as text downstream


class SecDataProvider(ABC):
    """Interface for a source of SEC company profiles + XBRL company facts."""

    name: str = "base"

    @abstractmethod
    def get_profile(self, ticker: str) -> CompanyProfile:
        """Resolve a ticker to a company profile."""

    @abstractmethod
    def get_company_facts(self, ticker: str) -> RawResponse:
        """Return the raw Company-Facts payload for a ticker.

        The payload follows the SEC companyfacts schema::

            {"cik": ..., "entityName": ..., "facts": {"us-gaap": {...}, "dei": {...}}}
        """


# --- Market data (used for abnormal-return signal inputs) ------------------
@dataclass
class PricePoint:
    date: date
    close: float
    volume: float | None = None


class MarketDataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_prices(self, ticker: str, lookback_days: int = 180) -> list[PricePoint]:
        """Return a chronological close-price series (may be synthetic/sample)."""


# --- Catalyst ingestion (manual in the MVP; adapter interface for the future) ---
@dataclass
class CatalystRecord:
    drug_program: str
    event_type: str
    indication: str | None = None
    trial_phase: str | None = None
    expected_date: date | None = None
    actual_date: date | None = None
    outcome: str = "pending"
    source_url: str | None = None
    notes: str | None = None
    source: str = "manual"
    extra: dict = field(default_factory=dict)


class CatalystProvider(ABC):
    """Automated catalyst sources plug in here.

    Implementations return a list of `CatalystRecord`s to be upserted. The live
    ClinicalTrials.gov adapter matches trials by sponsor name, so `company_name`
    is provided alongside the ticker; implementations that key off the ticker
    (or return nothing) may ignore it.
    """

    name: str = "manual"

    @abstractmethod
    def fetch(self, ticker: str, company_name: str | None = None) -> list[CatalystRecord]:
        ...


# --- Analyst coverage (ratings + price targets from covering institutions) ---
@dataclass
class AnalystRatingRecord:
    """One institution's view of a company."""

    institution: str
    grade: str | None = None          # e.g. "Overweight", "Buy"
    action: str | None = None         # upgrade|downgrade|initiate|maintain|target
    price_target: float | None = None
    rating_date: date | None = None
    external_id: str | None = None    # stable dedupe key when available


@dataclass
class AnalystConsensusData:
    """Aggregate coverage used to drive the signal engine."""

    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0
    consensus_label: str | None = None
    target_high: float | None = None
    target_low: float | None = None
    target_consensus: float | None = None
    target_median: float | None = None
    current_price: float | None = None
    analyst_count: int = 0
    as_of_date: date | None = None


@dataclass
class AnalystData:
    consensus: AnalystConsensusData
    ratings: list[AnalystRatingRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class AnalystDataProvider(ABC):
    """Source of analyst ratings + price targets (mock or a licensed API)."""

    name: str = "base"

    @abstractmethod
    def fetch(self, ticker: str) -> AnalystData:
        ...


# --- News (headlines; sentiment is provider-supplied or heuristic downstream) ---
@dataclass
class NewsItem:
    external_id: str
    headline: str
    summary: str | None = None
    source: str | None = None          # publisher
    url: str | None = None
    published_at: datetime | None = None
    related: str | None = None
    # Provider sentiment, when the source supplies it; None → compute a heuristic.
    sentiment_label: str | None = None
    sentiment_score: float | None = None


class NewsProvider(ABC):
    """Source of company news headlines (mock or a licensed API)."""

    name: str = "base"

    @abstractmethod
    def fetch(self, ticker: str, lookback_days: int = 30, max_articles: int = 40) -> list[NewsItem]:
        ...
