"""Provider interfaces and transport dataclasses.

Design goal: make data sources swappable. The mock and the live SEC adapter both
emit the *same* Company-Facts-shaped payload, so a single normalizer
(`app.services.normalization`) works regardless of which provider produced it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


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
    """Future automated catalyst sources plug in here.

    The MVP ships only a manual provider (returns nothing to fetch); real
    adapters (e.g. an authorized ClinicalTrials.gov client) implement `fetch`.
    """

    name: str = "manual"

    @abstractmethod
    def fetch(self, ticker: str) -> list[CatalystRecord]:
        ...
