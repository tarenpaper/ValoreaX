"""Catalyst ingestion: provider → cache → raw store → idempotent upsert.

Fetches trial catalysts from the configured `CatalystProvider` and upserts them
as `CatalystEvent`s. Design guarantees:

  * **Idempotent** — keyed on (company_id, source, external_id); re-running
    refreshes scheduling fields in place rather than duplicating.
  * **Human data is sacred** — a manually recorded ``actual_date`` / ``outcome``
    is never overwritten by auto-ingest, and manual events (external_id NULL)
    are left completely untouched.
  * **Provenance** — the exact fetched records are stored verbatim in
    RawProviderResponse (resource_type="clinical_trials"), separate from the
    normalized CatalystEvent rows.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import select

from app.models import CatalystEvent, RawProviderResponse
from app.providers.base import CatalystProvider, CatalystRecord

from .cache_service import CacheService

# Fields refreshed on an existing auto-ingested event. Deliberately excludes
# actual_date and outcome so human-recorded resolutions survive re-ingestion.
_REFRESHABLE = ("drug_program", "indication", "event_type", "trial_phase",
                "expected_date", "source_url", "notes")


@dataclass
class CatalystIngestionResult:
    provider: str
    fetched: int
    added: int
    updated: int
    skipped: int
    was_cached: bool
    warnings: list[str]


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _serialize(records: list[CatalystRecord]) -> dict:
    out = []
    for r in records:
        d = asdict(r)
        d["expected_date"] = _iso(r.expected_date)
        d["actual_date"] = _iso(r.actual_date)
        out.append(d)
    return {"records": out}


def _deserialize(payload: dict) -> list[CatalystRecord]:
    records = []
    for d in payload.get("records", []):
        records.append(
            CatalystRecord(
                drug_program=d["drug_program"],
                event_type=d["event_type"],
                indication=d.get("indication"),
                trial_phase=d.get("trial_phase"),
                expected_date=_parse_date(d.get("expected_date")),
                actual_date=_parse_date(d.get("actual_date")),
                outcome=d.get("outcome", "pending"),
                source_url=d.get("source_url"),
                notes=d.get("notes"),
                source=d.get("source", "manual"),
                extra=d.get("extra", {}) or {},
            )
        )
    return records


def _store_raw(session, provider: str, resource_key: str, payload: dict) -> None:
    text = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(text.encode()).hexdigest()
    existing = session.execute(
        select(RawProviderResponse).where(RawProviderResponse.content_hash == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(RawProviderResponse(
        provider=provider, resource_type="clinical_trials", resource_key=resource_key,
        content_hash=digest, payload=text,
    ))
    session.flush()


def ingest_catalysts(session, company, provider: CatalystProvider, cache: CacheService,
                     config) -> CatalystIngestionResult:
    """Fetch and upsert catalysts for one company from the configured provider."""
    ttl = config.get("CACHE_TTL_CLINICAL_TRIALS", 21_600)
    cache_key = f"{provider.name}:{company.cik or company.ticker}"

    # Only serve/keep meaningful pulls: an empty result (e.g. a sponsor-name miss)
    # is never cached, and a previously-cached empty one is refetched.
    cached = cache.get("clinical_trials", cache_key)
    if cached is not None and cached.get("records"):
        payload, was_cached = cached, True
    else:
        payload = _serialize(provider.fetch(company.ticker, company_name=company.name))
        was_cached = False
        if payload.get("records"):
            cache.set("clinical_trials", cache_key, payload, ttl, provider=provider.name)

    _store_raw(session, provider.name, cache_key, payload)
    records = _deserialize(payload)

    # Existing auto-ingested events for this company/source, indexed by external_id.
    existing = session.execute(
        select(CatalystEvent).where(
            CatalystEvent.company_id == company.id,
            CatalystEvent.external_id.is_not(None),
        )
    ).scalars().all()
    by_key = {(e.source, e.external_id): e for e in existing}

    added = updated = skipped = 0
    warnings: list[str] = []
    for r in records:
        external_id = (r.extra or {}).get("nct_id")
        if not external_id:
            skipped += 1
            continue
        key = (r.source, external_id)
        event = by_key.get(key)
        if event is None:
            session.add(CatalystEvent(
                company_id=company.id, source=r.source, external_id=external_id,
                drug_program=r.drug_program, indication=r.indication, event_type=r.event_type,
                trial_phase=r.trial_phase, expected_date=r.expected_date,
                actual_date=r.actual_date, outcome=r.outcome,
                source_url=r.source_url, notes=r.notes,
            ))
            added += 1
        else:
            changed = False
            incoming = {
                "drug_program": r.drug_program, "indication": r.indication,
                "event_type": r.event_type, "trial_phase": r.trial_phase,
                "expected_date": r.expected_date, "source_url": r.source_url, "notes": r.notes,
            }
            for attr in _REFRESHABLE:
                if getattr(event, attr) != incoming[attr]:
                    setattr(event, attr, incoming[attr])
                    changed = True
            if changed:
                updated += 1
            else:
                skipped += 1

    session.commit()

    if provider.name == "clinicaltrials":
        warnings.append(
            "Trials were matched to this issuer by sponsor NAME, which is approximate. "
            "Verify each NCT id against the company's own disclosures."
        )
    if records and provider.name == "mock":
        warnings.append("Provider is 'mock' — these are illustrative SAMPLE catalysts, not real trials.")

    return CatalystIngestionResult(
        provider=provider.name, fetched=len(records), added=added, updated=updated,
        skipped=skipped, was_cached=was_cached, warnings=warnings,
    )
