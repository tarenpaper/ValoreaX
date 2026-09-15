"""SQLAlchemy models.

Importing this package registers every model on the shared metadata so
`db.create_all()` sees them.
"""
from __future__ import annotations

from .analyst import AnalystConsensus, AnalystRating
from .benchmark_price import BenchmarkPrice
from .cache_entry import CacheEntry
from .catalyst import CatalystEvent
from .common import (
    CatalystEventType,
    CatalystOutcome,
    MetricStatus,
    SignalType,
)
from .company import Company
from .drug import DrugAsset, ProductRevenue
from .filing import Filing, RawProviderResponse
from .financial_metric import FinancialMetric
from .market_price import MarketPrice
from .news import NewsArticle
from .signal_run import SignalRun

__all__ = [
    "AnalystConsensus",
    "AnalystRating",
    "BenchmarkPrice",
    "CacheEntry",
    "CatalystEvent",
    "CatalystEventType",
    "CatalystOutcome",
    "Company",
    "DrugAsset",
    "Filing",
    "FinancialMetric",
    "ProductRevenue",
    "MarketPrice",
    "MetricStatus",
    "NewsArticle",
    "RawProviderResponse",
    "SignalRun",
    "SignalType",
]
