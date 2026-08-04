"""Deterministic synthetic market-price provider (clearly labelled sample data).

Generates a stable pseudo-random walk seeded by the ticker so results are
reproducible. Used only to demonstrate the abnormal-return signal input; it is
never presented as real market data. Swap in a licensed market-data adapter by
implementing ``MarketDataProvider``.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta

from .base import MarketDataProvider, PricePoint


class MockMarketProvider(MarketDataProvider):
    name = "mock"

    def _seed(self, ticker: str) -> int:
        digest = hashlib.sha256(ticker.upper().encode()).hexdigest()
        return int(digest[:8], 16)

    def get_prices(self, ticker: str, lookback_days: int = 180) -> list[PricePoint]:
        seed = self._seed(ticker)
        base = 20.0 + (seed % 180)          # starting price in [20, 200)
        drift = ((seed >> 8) % 7 - 3) / 5000.0  # small daily drift
        vol = 0.012 + ((seed >> 16) % 20) / 1000.0
        today = date.today()
        prices: list[PricePoint] = []
        price = base
        for i in range(lookback_days, -1, -1):
            d = today - timedelta(days=i)
            if d.weekday() >= 5:  # skip weekends
                continue
            # Deterministic "noise" from a sinusoid of the day index + seed.
            noise = math.sin((i * 2.399963 + seed) % (2 * math.pi)) * vol
            price = max(1.0, price * (1 + drift + noise))
            prices.append(PricePoint(date=d, close=round(price, 2)))
        return prices
