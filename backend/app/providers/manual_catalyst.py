"""Manual catalyst 'provider'.

The MVP populates catalysts via the CRUD API only — we do not scrape or invent
events. This class satisfies the CatalystProvider interface (returning nothing to
auto-ingest) so a future authorized adapter can drop in without API changes.
"""
from __future__ import annotations

from .base import CatalystProvider, CatalystRecord


class ManualCatalystProvider(CatalystProvider):
    name = "manual"

    def fetch(self, ticker: str, company_name: str | None = None) -> list[CatalystRecord]:
        # Intentionally empty: manual entry only.
        return []
