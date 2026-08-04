"""Twelve Data daily market-price provider.

The adapter calls Twelve Data's ``/time_series`` endpoint with a 1-day interval
and stores the returned close and volume observations. Configure the API key only
through the environment; no key is committed to the repository.
"""
from __future__ import annotations

from datetime import date, timedelta

import requests

from .base import MarketDataProvider, PricePoint, ProviderError


class TwelveDataMarketProvider(MarketDataProvider):
    """Fetch recent daily close/volume history from Twelve Data."""

    name = "twelve_data_daily"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.twelvedata.com",
        timeout_seconds: int = 20,
    ) -> None:
        if not api_key or api_key.lower() in {"change_me", "your_api_key", "demo"}:
            raise ProviderError(
                "TWELVE_DATA_API_KEY is required when MARKET_DATA_PROVIDER=twelve_data."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_prices(self, ticker: str, lookback_days: int = 90) -> list[PricePoint]:
        """Return chronological daily close prices for a recent calendar window."""
        symbol = ticker.strip().upper()
        if not symbol:
            raise ProviderError("A non-empty ticker is required for market-price retrieval.")
        outputsize = max(30, min(5_000, lookback_days * 2))
        try:
            response = requests.get(
                f"{self.base_url}/time_series",
                params={
                    "symbol": symbol,
                    "interval": "1day",
                    "outputsize": outputsize,
                    "apikey": self.api_key,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"Twelve Data request failed for {symbol}: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(f"Twelve Data returned invalid JSON for {symbol}.") from exc

        if payload.get("status") == "error":
            raise ProviderError(
                f"Twelve Data could not serve {symbol}: {payload.get('message', 'unknown error')}"
            )
        values = payload.get("values")
        if not isinstance(values, list) or not values:
            raise ProviderError(f"Twelve Data returned no daily price series for {symbol}.")

        cutoff = date.today() - timedelta(days=max(1, lookback_days))
        points: list[PricePoint] = []
        for value in values:
            try:
                observed_on = date.fromisoformat(value["datetime"][:10])
                close = float(value["close"])
                volume = float(value["volume"]) if value.get("volume") else None
            except (KeyError, TypeError, ValueError):
                continue
            if observed_on >= cutoff and close > 0:
                points.append(PricePoint(date=observed_on, close=close, volume=volume))

        points.sort(key=lambda point: point.date)
        if len(points) < 2:
            raise ProviderError(
                f"Twelve Data returned fewer than two usable daily prices for {symbol}."
            )
        return points
