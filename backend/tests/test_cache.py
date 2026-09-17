"""Tests for the TTL cache service."""
from __future__ import annotations

from datetime import UTC, timedelta

from app.models import CacheEntry
from app.models.common import utcnow
from app.services import CacheService


def test_set_and_get_roundtrip(db):
    cache = CacheService(db.session)
    cache.set("company_facts", "CIK1", {"a": 1}, ttl=3600)
    assert cache.get("company_facts", "CIK1") == {"a": 1}


def test_miss_returns_none(db):
    cache = CacheService(db.session)
    assert cache.get("company_facts", "nope") is None
    assert cache.last_ttl_remaining is None


def test_expired_entry_is_a_miss_and_evicted(db):
    cache = CacheService(db.session)
    cache.set("prices", "K", {"v": 1}, ttl=3600)
    entry = db.session.query(CacheEntry).filter_by(namespace="prices", key="K").one()
    entry.expires_at = utcnow() - timedelta(seconds=1)  # force expiry
    db.session.commit()
    assert cache.get("prices", "K") is None
    assert cache.last_ttl_remaining is None
    assert db.session.query(CacheEntry).filter_by(namespace="prices", key="K").count() == 0


def test_get_records_remaining_ttl_without_a_second_query(db, monkeypatch):
    cache = CacheService(db.session)
    cache.set("prices", "K", {"v": 1}, ttl=3600)
    entry = db.session.query(CacheEntry).filter_by(namespace="prices", key="K").one()
    later = entry.expires_at.replace(tzinfo=UTC) - timedelta(seconds=90)
    monkeypatch.setattr("app.services.cache_service.utcnow", lambda: later)
    assert cache.get("prices", "K") == {"v": 1}
    assert cache.last_ttl_remaining == 90


def test_get_or_set_calls_loader_only_on_miss(db):
    cache = CacheService(db.session)
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return {"loaded": True}

    v1, cached1 = cache.get_or_set("ns", "k", 3600, loader)
    v2, cached2 = cache.get_or_set("ns", "k", 3600, loader)
    assert v1 == v2 == {"loaded": True}
    assert cached1 is False and cached2 is True
    assert calls["n"] == 1


def test_invalidate_single_key(db):
    cache = CacheService(db.session)
    cache.set("ns", "a", {"x": 1}, ttl=3600)
    cache.set("ns", "b", {"x": 2}, ttl=3600)
    assert cache.invalidate("ns", "a") == 1
    assert cache.get("ns", "a") is None
    assert cache.get("ns", "b") == {"x": 2}


def test_invalidate_namespace(db):
    cache = CacheService(db.session)
    cache.set("ns", "a", {"x": 1}, ttl=3600)
    cache.set("ns", "b", {"x": 2}, ttl=3600)
    assert cache.invalidate("ns") == 2
    assert cache.get("ns", "a") is None and cache.get("ns", "b") is None


def test_no_ttl_never_expires(db):
    cache = CacheService(db.session)
    cache.set("ns", "forever", {"x": 1}, ttl=None)
    entry = db.session.query(CacheEntry).filter_by(namespace="ns", key="forever").one()
    assert entry.expires_at is None
    assert cache.get("ns", "forever") == {"x": 1}
    assert cache.last_ttl_remaining is None
