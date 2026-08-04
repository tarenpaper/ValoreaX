"""SQLAlchemy models.

Importing this package registers every model on the shared metadata so
`db.create_all()` sees them.
"""
from __future__ import annotations

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
from .filing import Filing, RawProviderResponse
from .financial_metric import FinancialMetric
from .market_price import MarketPrice
from .signal_run import SignalRun

__all__ = [
    "BenchmarkPrice",
    "CacheEntry",
    "CatalystEvent",
    "CatalystEventType",
    "CatalystOutcome",
    "Company",
    "Filing",
    "FinancialMetric",
    "MarketPrice",
    "MetricStatus",
    "RawProviderResponse",
    "SignalRun",
    "SignalType",
]
