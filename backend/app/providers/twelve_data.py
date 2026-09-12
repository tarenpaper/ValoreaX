"""Twelve Data daily market-price provider.

The adapter calls Twelve Data's ``/time_series`` endpoint with a 1-day interval
and stores the returned close and volume observations. Configure the API key only
through the environment; no key is committed to the repository.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import isfinite

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

    def get_history(self, ticker: str, start: date, end: date) -> list[PricePoint]:
        """Bounded, split-adjusted daily history, independent of today's lookback window."""
        symbol = ticker.strip().upper()
        try:
            response = requests.get(
                f"{self.base_url}/time_series",
                params={"symbol": symbol, "interval": "1day", "start_date": start.isoformat(),
                        # Include the requested final session even for exclusive date boundaries.
                        "end_date": (end + timedelta(days=1)).isoformat(), "outputsize": 5000,
                        "order": "ASC", "adjust": "splits", "apikey": self.api_key},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"Historical prices unavailable for {symbol}. Check provider access and connectivity.") from exc
        if not isinstance(payload, dict) or payload.get("status") == "error":
            raise ProviderError(f"Historical prices unavailable for {symbol}. The provider may have a plan or rate limit.")
        currency = payload.get("meta", {}).get("currency")
        if currency and currency != "USD":
            raise ProviderError("This dollar simulation currently supports USD-priced instruments only.")
        rows = payload.get("values")
        if not isinstance(rows, list) or not rows:
            raise ProviderError(f"No historical prices returned for {symbol} in this period.")
        if len(rows) >= 5000:
            raise ProviderError("History reached the provider's row limit. Choose a shorter period.")
        points = {}
        for row in rows:
            try:
                day = date.fromisoformat(row["datetime"][:10])
                close = float(row["close"])
            except (ValueError, TypeError, KeyError) as exc:
                raise ProviderError(f"Malformed historical price returned for {symbol}.") from exc
            if not start <= day <= end:
                continue
            if not isfinite(close) or close <= 0:
                raise ProviderError(f"Invalid historical price returned for {symbol}.")
            if day in points and points[day].close != close:
                raise ProviderError(f"Conflicting historical prices returned for {symbol}.")
            points[day] = PricePoint(date=day, close=close)
        if len(points) < 2:
            raise ProviderError(f"Fewer than two historical closing prices available for {symbol}.")
        return [points[day] for day in sorted(points)]

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
            raise ProviderError(f"Twelve Data request failed for {symbol}. Check connectivity, credentials, and plan access.") from exc
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
