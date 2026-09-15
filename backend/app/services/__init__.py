"""Business-logic services (pure where possible, DB-aware where needed)."""
from __future__ import annotations

from .cache_service import CacheService
from .ingestion_service import IngestionResult, ingest_company
from .normalization import (
    PRIMARY_CONCEPTS,
    NormalizationResult,
    normalize_company_facts,
)
from .signals import SignalInputs, SignalResult, score_signal

__all__ = [
    "CacheService",
    "IngestionResult",
    "NormalizationResult",
    "PRIMARY_CONCEPTS",
    "SignalInputs",
    "SignalResult",
    "ingest_company",
    "normalize_company_facts",
    "score_signal",
]
