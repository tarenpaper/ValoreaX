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
from .valuation import (
    DcfAssumptions,
    DcfInputs,
    DcfResult,
    ScenarioDeltas,
    ValuationError,
    run_dcf,
    run_scenarios,
    sensitivity_grid,
)

__all__ = [
    "CacheService",
    "DcfAssumptions",
    "DcfInputs",
    "DcfResult",
    "IngestionResult",
    "NormalizationResult",
    "PRIMARY_CONCEPTS",
    "ScenarioDeltas",
    "SignalInputs",
    "SignalResult",
    "ValuationError",
    "ingest_company",
    "normalize_company_facts",
    "run_dcf",
    "run_scenarios",
    "score_signal",
    "sensitivity_grid",
]
