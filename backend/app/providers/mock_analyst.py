"""Deterministic, offline mock analyst provider.

Produces **fictional sample** coverage (rating distribution, price targets, and a
few named-institution rows) that mirrors the shape the live FMP adapter returns,
so the ingestion path, signal engine, and tests run with zero network access.
Clearly not real: institutions are illustrative and values are seeded, not sourced.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from .base import AnalystConsensusData, AnalystData, AnalystDataProvider, AnalystRatingRecord

_INSTITUTIONS = [
    "Morgan Stanley", "Goldman Sachs", "JPMorgan", "BofA Securities",
    "Barclays", "UBS", "Jefferies", "Citi", "Wells Fargo", "Evercore ISI",
]
_BUY_GRADES = ["Overweight", "Buy", "Outperform"]
_HOLD_GRADES = ["Hold", "Neutral", "Equal-Weight"]
_SELL_GRADES = ["Underweight", "Sell"]


def _seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:8], 16)


def _label(sb: int, b: int, h: int, s: int, ss: int) -> str:
    total = sb + b + h + s + ss
    if not total:
        return "Hold"
    score = (sb * 2 + b - s - ss * 2) / total
    if score >= 1.0:
        return "Strong Buy"
    if score >= 0.25:
        return "Buy"
    if score > -0.25:
        return "Hold"
    if score > -1.0:
        return "Sell"
    return "Strong Sell"


class MockAnalystProvider(AnalystDataProvider):
    name = "mock"

    def fetch(self, ticker: str) -> AnalystData:
        seed = _seed(ticker)
        bull = (seed % 1000) / 1000.0            # 0..1 bullishness
        total = 8 + (seed % 11)                  # 8..18 analysts
        strong_buy = round(total * bull * 0.5)
        buy = round(total * bull * 0.4)
        strong_sell = round(total * (1 - bull) * 0.25)
        sell = round(total * (1 - bull) * 0.35)
        hold = max(0, total - strong_buy - buy - sell - strong_sell)

        current_price = round(20 + (seed % 180) + (seed % 100) / 100.0, 2)
        upside = -0.15 + bull * 0.5              # -15%..+35%
        target_consensus = round(current_price * (1 + upside), 2)
        target_high = round(target_consensus * 1.15, 2)
        target_low = round(target_consensus * 0.85, 2)
        target_median = round(target_consensus * 1.01, 2)
        today = date.today()

        consensus = AnalystConsensusData(
            strong_buy=strong_buy, buy=buy, hold=hold, sell=sell, strong_sell=strong_sell,
            consensus_label=_label(strong_buy, buy, hold, sell, strong_sell),
            target_high=target_high, target_low=target_low,
            target_consensus=target_consensus, target_median=target_median,
            current_price=current_price, analyst_count=total, as_of_date=today,
        )

        # A few illustrative per-institution rows, deterministic per ticker.
        ratings: list[AnalystRatingRecord] = []
        for i in range(5):
            inst = _INSTITUTIONS[(seed + i) % len(_INSTITUTIONS)]
            pick = (bull * 100 + i * 13) % 100
            grade = (_BUY_GRADES if pick > 45 else _HOLD_GRADES if pick > 20 else _SELL_GRADES)[i % 3]
            target = round(target_consensus * (0.9 + ((seed + i) % 20) / 100.0), 2)
            ratings.append(AnalystRatingRecord(
                institution=inst, grade=grade, action="maintain", price_target=target,
                rating_date=today - timedelta(days=i * 9),
                external_id=f"mock-{ticker.upper()}-{i}",
            ))
        return AnalystData(consensus=consensus, ratings=ratings,
                           warnings=["Provider is 'mock' — illustrative SAMPLE analyst data, not real."])
