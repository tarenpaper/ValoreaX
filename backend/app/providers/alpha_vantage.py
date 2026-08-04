"""Alpha Vantage daily market-price provider.

This adapter uses the documented ``TIME_SERIES_DAILY`` endpoint, whose compact
response contains the most recent 100 trading sessions. It intentionally stores
unadjusted closing prices: this is appropriate for short event windows, but is
not a total-return series and must not be used for long-horizon performance
claims. Configure the API key only through the environment.
"""
from __future__ import annotations

from datetime import date, timedelta

import requests

from .base import MarketDataProvider, PricePoint, ProviderError


class AlphaVantageMarketProvider(MarketDataProvider):
    """Fetch recent daily close/volume history from Alpha Vantage."""

    name = "alpha_vantage_daily_close"
    _SERIES_KEY = "Time Series (Daily)"

    def __init__(self, api_key: str, base_url: str = "https://www.alphavantage.co/query",
                 timeout_seconds: int = 20) -> None:
        if not api_key or api_key.lower() in {"change_me", "your_api_key", "demo"}:
            raise ProviderError(
                "ALPHA_VANTAGE_API_KEY is required when MARKET_DATA_PROVIDER=alpha_vantage."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_prices(self, ticker: str, lookback_days: int = 90) -> list[PricePoint]:
        """Return recent chronological daily close prices.

        Alpha Vantage's compact daily endpoint returns at most 100 trading days,
        so callers should use short event windows and keep the configured lookback
        at or below roughly 90 calendar days.
        """
        symbol = ticker.strip().upper()
        if not symbol:
            raise ProviderError("A non-empty ticker is required for market-price retrieval.")
        try:
            response = requests.get(
                self.base_url,
                params={
                    "function": "TIME_SERIES_DAILY",
                    "symbol": symbol,
                    "outputsize": "compact",
                    "datatype": "json",
                    "apikey": self.api_key,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"Alpha Vantage request failed for {symbol}: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(f"Alpha Vantage returned invalid JSON for {symbol}.") from exc

        message = payload.get("Error Message") or payload.get("Information") or payload.get("Note")
        if message:
            raise ProviderError(f"Alpha Vantage could not serve {symbol}: {message}")
        series = payload.get(self._SERIES_KEY)
        if not isinstance(series, dict) or not series:
            raise ProviderError(f"Alpha Vantage returned no daily price series for {symbol}.")

        cutoff = date.today() - timedelta(days=max(1, lookback_days))
        points: list[PricePoint] = []
        for raw_day, values in series.items():
            try:
                observed_on = date.fromisoformat(raw_day)
                close = float(values["4. close"])
                volume = float(values["5. volume"]) if values.get("5. volume") else None
            except (KeyError, TypeError, ValueError):
                continue
            if observed_on >= cutoff and close > 0:
                points.append(PricePoint(date=observed_on, close=close, volume=volume))

        points.sort(key=lambda point: point.date)
        if len(points) < 2:
            raise ProviderError(
                f"Alpha Vantage returned fewer than two usable daily prices for {symbol}."
            )
        return points
