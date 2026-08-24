"""Deterministic, offline mock catalyst provider.

Emits **fictional sample** `CatalystRecord`s that mirror the shape the live
ClinicalTrials.gov adapter produces (pending trial milestones with expected
dates, synthetic NCT-style ids, and a source URL), so the ingestion path and
tests exercise the same code with zero network access.

Like every mock here, nothing is presented as real: notes are tagged "(SAMPLE)"
and outcomes are always ``pending`` (we never fabricate clinical results).
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from .base import CatalystProvider, CatalystRecord

# A small deterministic set of trial "templates" keyed off a per-ticker seed, so
# any ticker yields stable, reproducible sample catalysts.
_TEMPLATES = [
    ("phase_readout", "Phase 2", "Metastatic solid tumors", -80),
    ("pdufa", "Filed", "Rare autoimmune disease", 45),
    ("trial_completion", "Phase 3", "Chronic inflammatory disease", 160),
]


def _seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:8], 16)


class MockCatalystProvider(CatalystProvider):
    """In-memory provider returning deterministic sample trial catalysts."""

    name = "mock"

    def fetch(self, ticker: str, company_name: str | None = None) -> list[CatalystRecord]:
        seed = _seed(ticker)
        today = date.today()
        records: list[CatalystRecord] = []
        for i, (event_type, phase, indication, day_offset) in enumerate(_TEMPLATES):
            nct = f"NCT9{seed % 10_000_000:07d}"[:11] + str(i)
            records.append(
                CatalystRecord(
                    drug_program=f"{ticker.upper()}-{100 + (seed % 900) + i}",
                    event_type=event_type,
                    indication=indication,
                    trial_phase=phase,
                    expected_date=today + timedelta(days=day_offset),
                    actual_date=None,
                    outcome="pending",
                    source_url=f"https://clinicaltrials.gov/study/{nct}",
                    notes="Illustrative SAMPLE trial catalyst — not a real clinical event.",
                    source=self.name,
                    extra={"nct_id": nct, "overall_status": "RECRUITING"},
                )
            )
        return records
