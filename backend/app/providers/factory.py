"""Provider selection.

Reads the current Flask app config and returns the configured provider
instances. This is the single seam to change when adding a new data source.

Instances are reused on ``current_app.extensions`` so process-local state
(the SEC ticker map, HTTP sessions) survives across requests in one worker.
The cache key includes the configured provider name, so a test that swaps
``SEC_PROVIDER`` still gets a fresh adapter.
"""
from __future__ import annotations

from flask import current_app

from .base import (
    AnalystDataProvider,
    CatalystProvider,
    MarketDataProvider,
    NewsProvider,
    SecDataProvider,
)
from .clinicaltrials import ClinicalTrialsCatalystProvider
from .finnhub_news import FinnhubNewsProvider
from .fmp_analyst import FmpAnalystProvider
from .manual_catalyst import ManualCatalystProvider
from .mock_analyst import MockAnalystProvider
from .mock_catalyst import MockCatalystProvider
from .mock_market import MockMarketProvider
from .mock_news import MockNewsProvider
from .mock_provider import MockSecProvider
from .sec_edgar import SecEdgarProvider
from .twelve_data import TwelveDataMarketProvider

_SEC_PROVIDERS = {
    "mock": lambda cfg: MockSecProvider(),
    "sec_edgar": lambda cfg: SecEdgarProvider(
        user_agent=cfg["SEC_USER_AGENT"],
        base_url=cfg["SEC_BASE_URL"],
        www_url=cfg["SEC_WWW_URL"],
    ),
}

_MARKET_PROVIDERS = {
    "mock": lambda cfg: MockMarketProvider(),
    "twelve_data": lambda cfg: TwelveDataMarketProvider(
        api_key=cfg["TWELVE_DATA_API_KEY"],
        base_url=cfg["TWELVE_DATA_BASE_URL"],
        timeout_seconds=cfg["MARKET_DATA_TIMEOUT_SECONDS"],
    ),
}

_CATALYST_PROVIDERS = {
    "manual": lambda cfg: ManualCatalystProvider(),
    "mock": lambda cfg: MockCatalystProvider(),
    "clinicaltrials": lambda cfg: ClinicalTrialsCatalystProvider(
        user_agent=cfg["CLINICALTRIALS_USER_AGENT"],
        base_url=cfg["CLINICALTRIALS_BASE_URL"],
        timeout=cfg["CLINICALTRIALS_TIMEOUT_SECONDS"],
        max_studies=cfg["CLINICALTRIALS_MAX_STUDIES"],
    ),
}

_ANALYST_PROVIDERS = {
    "mock": lambda cfg: MockAnalystProvider(),
    "fmp": lambda cfg: FmpAnalystProvider(
        api_key=cfg["FMP_API_KEY"],
        base_url=cfg["FMP_BASE_URL"],
        timeout=cfg["FMP_TIMEOUT_SECONDS"],
    ),
}

_NEWS_PROVIDERS = {
    "mock": lambda cfg: MockNewsProvider(),
    "finnhub": lambda cfg: FinnhubNewsProvider(
        api_key=cfg["FINNHUB_API_KEY"],
        base_url=cfg["FINNHUB_BASE_URL"],
        timeout=cfg["FINNHUB_TIMEOUT_SECONDS"],
    ),
}


def _cached_provider(kind: str, mapping: dict, config_key: str, default: str, label: str):
    cfg = current_app.config
    name = cfg.get(config_key, default)
    factory = mapping.get(name)
    if factory is None:
        raise ValueError(f"Unknown {label}={name!r}. Options: {sorted(mapping)}")
    cache = current_app.extensions.setdefault("data_providers", {})
    cached = cache.get(kind)
    if cached is not None and cached[0] == name:
        return cached[1]
    instance = factory(cfg)
    cache[kind] = (name, instance)
    return instance


def get_sec_provider() -> SecDataProvider:
    return _cached_provider("sec", _SEC_PROVIDERS, "SEC_PROVIDER", "mock", "SEC_PROVIDER")


def get_market_provider() -> MarketDataProvider:
    return _cached_provider(
        "market", _MARKET_PROVIDERS, "MARKET_DATA_PROVIDER", "mock", "MARKET_DATA_PROVIDER"
    )


def get_catalyst_provider() -> CatalystProvider:
    return _cached_provider(
        "catalyst", _CATALYST_PROVIDERS, "CATALYST_PROVIDER", "manual", "CATALYST_PROVIDER"
    )


def get_analyst_provider() -> AnalystDataProvider:
    return _cached_provider(
        "analyst", _ANALYST_PROVIDERS, "ANALYST_PROVIDER", "mock", "ANALYST_PROVIDER"
    )


def get_news_provider() -> NewsProvider:
    return _cached_provider("news", _NEWS_PROVIDERS, "NEWS_PROVIDER", "mock", "NEWS_PROVIDER")
