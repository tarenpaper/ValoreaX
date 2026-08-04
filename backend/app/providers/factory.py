"""Provider selection.

Reads the current Flask app config and returns the configured provider
instances. This is the single seam to change when adding a new data source.
"""
from __future__ import annotations

from flask import current_app

from .base import CatalystProvider, MarketDataProvider, SecDataProvider
from .manual_catalyst import ManualCatalystProvider
from .mock_market import MockMarketProvider
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
    return ManualCatalystProvider()
