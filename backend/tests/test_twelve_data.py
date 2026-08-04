"""Tests for the Twelve Data provider without a live API key."""
from __future__ import annotations

import pytest

from app.providers.base import ProviderError
from app.providers.twelve_data import TwelveDataMarketProvider


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_rejects_missing_api_key():
    with pytest.raises(ProviderError, match="TWELVE_DATA_API_KEY"):
        TwelveDataMarketProvider(api_key="")


def test_parses_daily_close_series(monkeypatch):
    payload = {
        "status": "ok",
        "values": [
            {"datetime": "2026-08-03", "close": "101.25", "volume": "1234"},
            {"datetime": "2026-08-02", "close": "100.00", "volume": "1200"},
        ],
    }
    monkeypatch.setattr(
        "app.providers.twelve_data.requests.get",
        lambda *args, **kwargs: _Response(payload),
    )
    provider = TwelveDataMarketProvider(api_key="test-key")
    points = provider.get_prices("test", lookback_days=10_000)

    assert [point.close for point in points] == [100.0, 101.25]
    assert points[-1].volume == 1234.0


def test_surfaces_provider_error_message(monkeypatch):
    monkeypatch.setattr(
        "app.providers.twelve_data.requests.get",
        lambda *args, **kwargs: _Response({"status": "error", "message": "rate limit"}),
    )
    provider = TwelveDataMarketProvider(api_key="test-key")

    with pytest.raises(ProviderError, match="rate limit"):
        provider.get_prices("TEST")
