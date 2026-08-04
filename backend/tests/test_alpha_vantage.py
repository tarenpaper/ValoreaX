"""Tests for the Alpha Vantage provider without a live API key."""
from __future__ import annotations

import pytest

from app.providers.alpha_vantage import AlphaVantageMarketProvider
from app.providers.base import ProviderError


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_rejects_missing_api_key():
    with pytest.raises(ProviderError, match="ALPHA_VANTAGE_API_KEY"):
        AlphaVantageMarketProvider(api_key="")


def test_parses_daily_close_series(monkeypatch):
    payload = {
        "Time Series (Daily)": {
            "2026-08-03": {"4. close": "101.25", "5. volume": "1234"},
            "2026-08-02": {"4. close": "100.00", "5. volume": "1200"},
        }
    }
    monkeypatch.setattr(
        "app.providers.alpha_vantage.requests.get",
        lambda *args, **kwargs: _Response(payload),
    )
    provider = AlphaVantageMarketProvider(api_key="test-key")
    points = provider.get_prices("test", lookback_days=365)

    assert [point.close for point in points] == [100.0, 101.25]
    assert points[-1].volume == 1234.0


def test_surfaces_provider_rate_limit_message(monkeypatch):
    monkeypatch.setattr(
        "app.providers.alpha_vantage.requests.get",
        lambda *args, **kwargs: _Response({"Note": "rate limit"}),
    )
    provider = AlphaVantageMarketProvider(api_key="test-key")

    with pytest.raises(ProviderError, match="rate limit"):
        provider.get_prices("TEST")
