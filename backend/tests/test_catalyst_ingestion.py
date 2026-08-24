"""Tests for catalyst ingestion (mock provider, offline)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import CatalystEvent, Company, RawProviderResponse
from app.providers.manual_catalyst import ManualCatalystProvider
from app.providers.mock_catalyst import MockCatalystProvider
from app.services.cache_service import CacheService
from app.services.catalyst_ingestion import ingest_catalysts

CONFIG = {"CACHE_TTL_CLINICAL_TRIALS": 3600}


def _company(db) -> Company:
    company = Company(ticker="VALX", name="Valorea Therapeutics", cik="0009000001", source="mock")
    db.session.add(company)
    db.session.commit()
    return company


def _events(db, company_id):
    return db.session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all()


def test_ingest_persists_records(db):
    company = _company(db)
    result = ingest_catalysts(db.session, company, MockCatalystProvider(), CacheService(db.session), CONFIG)

    assert result.fetched == 3
    assert result.added == 3
    events = _events(db, company.id)
    assert len(events) == 3
    assert all(e.source == "mock" and e.external_id for e in events)
    assert all(e.outcome == "pending" for e in events)          # never fabricated
    assert all(e.source_url.startswith("https://clinicaltrials.gov/study/") for e in events)


def test_ingest_is_idempotent(db):
    company = _company(db)
    provider, cache = MockCatalystProvider(), CacheService(db.session)
    ingest_catalysts(db.session, company, provider, cache, CONFIG)
    second = ingest_catalysts(db.session, company, provider, cache, CONFIG)

    assert second.added == 0
    assert second.updated == 0
    assert len(_events(db, company.id)) == 3   # no duplicates


def test_reingest_refreshes_scheduling_fields(db):
    company = _company(db)
    provider, cache = MockCatalystProvider(), CacheService(db.session)
    ingest_catalysts(db.session, company, provider, cache, CONFIG)

    # A drifted scheduling field should be corrected on the next ingest.
    event = _events(db, company.id)[0]
    event.expected_date = date(1999, 1, 1)
    db.session.commit()

    result = ingest_catalysts(db.session, company, provider, cache, CONFIG)
    assert result.updated == 1
    assert db.session.get(CatalystEvent, event.id).expected_date != date(1999, 1, 1)


def test_manual_events_are_untouched(db):
    company = _company(db)
    manual = CatalystEvent(
        company_id=company.id, source="manual", external_id=None,
        drug_program="VLX-MANUAL", event_type="pdufa", outcome="pending",
    )
    db.session.add(manual)
    db.session.commit()

    ingest_catalysts(db.session, company, MockCatalystProvider(), CacheService(db.session), CONFIG)

    events = _events(db, company.id)
    assert len(events) == 4                       # 1 manual + 3 ingested
    still_manual = db.session.get(CatalystEvent, manual.id)
    assert still_manual.source == "manual" and still_manual.external_id is None


def test_human_recorded_outcome_survives_reingest(db):
    company = _company(db)
    provider, cache = MockCatalystProvider(), CacheService(db.session)
    ingest_catalysts(db.session, company, provider, cache, CONFIG)

    # A human resolves one auto-ingested catalyst.
    event = _events(db, company.id)[0]
    event.outcome = "positive"
    event.actual_date = date(2026, 1, 15)
    db.session.commit()

    ingest_catalysts(db.session, company, provider, cache, CONFIG)

    refreshed = db.session.get(CatalystEvent, event.id)
    assert refreshed.outcome == "positive"          # not reset to pending
    assert refreshed.actual_date == date(2026, 1, 15)


def test_raw_payload_is_stored(db):
    company = _company(db)
    ingest_catalysts(db.session, company, MockCatalystProvider(), CacheService(db.session), CONFIG)
    raw = db.session.execute(
        select(RawProviderResponse).where(RawProviderResponse.resource_type == "clinical_trials")
    ).scalars().all()
    assert len(raw) == 1


def test_manual_provider_fetches_nothing(db):
    company = _company(db)
    result = ingest_catalysts(db.session, company, ManualCatalystProvider(), CacheService(db.session), CONFIG)
    assert result.fetched == 0
    assert result.added == 0
    assert _events(db, company.id) == []
