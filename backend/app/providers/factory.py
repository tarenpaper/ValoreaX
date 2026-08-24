"""Provider selection.

Reads the current Flask app config and returns the configured provider
instances. This is the single seam to change when adding a new data source.
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


def get_sec_provider() -> SecDataProvider:
    cfg = current_app.config
    name = cfg.get("SEC_PROVIDER", "mock")
    factory = _SEC_PROVIDERS.get(name)
    if factory is None:
        raise ValueError(f"Unknown SEC_PROVIDER={name!r}. Options: {sorted(_SEC_PROVIDERS)}")
    return factory(cfg)


def get_market_provider() -> MarketDataProvider:
    cfg = current_app.config
    name = cfg.get("MARKET_DATA_PROVIDER", "mock")
    factory = _MARKET_PROVIDERS.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown MARKET_DATA_PROVIDER={name!r}. Options: {sorted(_MARKET_PROVIDERS)}"
        )
    return factory(cfg)


def get_catalyst_provider() -> CatalystProvider:
    cfg = current_app.config
    name = cfg.get("CATALYST_PROVIDER", "manual")
    factory = _CATALYST_PROVIDERS.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown CATALYST_PROVIDER={name!r}. Options: {sorted(_CATALYST_PROVIDERS)}"
        )
    return factory(cfg)


def get_analyst_provider() -> AnalystDataProvider:
    cfg = current_app.config
    name = cfg.get("ANALYST_PROVIDER", "mock")
    factory = _ANALYST_PROVIDERS.get(name)
    if factory is None:
        raise ValueError(f"Unknown ANALYST_PROVIDER={name!r}. Options: {sorted(_ANALYST_PROVIDERS)}")
    return factory(cfg)


def get_news_provider() -> NewsProvider:
    cfg = current_app.config
    name = cfg.get("NEWS_PROVIDER", "mock")
    factory = _NEWS_PROVIDERS.get(name)
    if factory is None:
        raise ValueError(f"Unknown NEWS_PROVIDER={name!r}. Options: {sorted(_NEWS_PROVIDERS)}")
    return factory(cfg)
