"""Tests for analyst-coverage ingestion + signal-input derivation (mock, offline)."""
from __future__ import annotations

from sqlalchemy import select

from app.models import AnalystConsensus, AnalystRating, Company, RawProviderResponse
from app.providers.mock_analyst import MockAnalystProvider
from app.services.analyst_ingestion import ingest_analyst_data
from app.services.cache_service import CacheService
from app.services.derivations import consensus_rating_score, derive_analyst_signal_inputs

CONFIG = {"CACHE_TTL_ANALYST": 3600}


def _company(db) -> Company:
    company = Company(ticker="VALX", name="Valorea Therapeutics", source="mock")
    db.session.add(company)
    db.session.commit()
    return company


def test_ingest_persists_consensus_and_ratings(db):
    company = _company(db)
    result = ingest_analyst_data(db.session, company, MockAnalystProvider(), CacheService(db.session), CONFIG)

    assert result.provider == "mock"
    assert result.analyst_count > 0
    assert result.rating_rows == 5
    consensus = db.session.execute(
        select(AnalystConsensus).where(AnalystConsensus.company_id == company.id)
    ).scalar_one()
    assert consensus.consensus_label is not None
    assert consensus.target_consensus and consensus.current_price
    ratings = db.session.execute(
        select(AnalystRating).where(AnalystRating.company_id == company.id)
    ).scalars().all()
    assert len(ratings) == 5
    assert all(r.institution for r in ratings)


def test_reingest_keeps_single_consensus_and_replaces_ratings(db):
    company = _company(db)
    provider, cache = MockAnalystProvider(), CacheService(db.session)
    ingest_analyst_data(db.session, company, provider, cache, CONFIG)
    ingest_analyst_data(db.session, company, provider, cache, CONFIG)

    consensus_rows = db.session.execute(
        select(AnalystConsensus).where(AnalystConsensus.company_id == company.id)
    ).scalars().all()
    rating_rows = db.session.execute(
        select(AnalystRating).where(AnalystRating.company_id == company.id)
    ).scalars().all()
    assert len(consensus_rows) == 1        # upserted, not duplicated
    assert len(rating_rows) == 5           # replaced, not appended


def test_raw_payload_stored(db):
    company = _company(db)
    ingest_analyst_data(db.session, company, MockAnalystProvider(), CacheService(db.session), CONFIG)
    raw = db.session.execute(
        select(RawProviderResponse).where(RawProviderResponse.resource_type == "analyst")
    ).scalars().all()
    assert len(raw) == 1


def test_consensus_rating_score_range():
    assert consensus_rating_score(10, 0, 0, 0, 0) == 1.0     # all Strong Buy
    assert consensus_rating_score(0, 0, 0, 0, 10) == -1.0    # all Strong Sell
    assert consensus_rating_score(0, 0, 10, 0, 0) == 0.0     # all Hold
    assert consensus_rating_score(0, 0, 0, 0, 0) is None     # no coverage


def test_derive_analyst_signal_inputs(db):
    company = _company(db)
    ingest_analyst_data(db.session, company, MockAnalystProvider(), CacheService(db.session), CONFIG)
    derived = derive_analyst_signal_inputs(db.session, company.id)

    assert derived["analyst_consensus"] is not None
    assert -1.0 <= derived["analyst_consensus"] <= 1.0
    assert derived["analyst_label"] is not None
    assert derived["analyst_target_upside"] is not None      # target vs current price


def test_derive_returns_empty_without_coverage(db):
    company = _company(db)
    assert derive_analyst_signal_inputs(db.session, company.id) == {}
