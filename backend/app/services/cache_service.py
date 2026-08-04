"""DB-backed TTL cache for non-time-sensitive provider data.

Strategy (see docs/CACHING.md):
  * key space is ``(namespace, key)`` — e.g. ("company_facts", "<CIK>")
  * each entry stores JSON text plus an ``expires_at`` timestamp
  * reads past ``expires_at`` are treated as misses (lazy expiry)
  * ``invalidate`` supports single-key and whole-namespace eviction
  * TTLs come from config: long for filings/profiles, short for prices
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.models import CacheEntry
from app.models.common import utcnow


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read; treat naive stored timestamps as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class CacheService:
    def __init__(self, session) -> None:
        self.session = session

    def get(self, namespace: str, key: str) -> dict | None:
        entry = self.session.execute(
            select(CacheEntry).where(CacheEntry.namespace == namespace, CacheEntry.key == key)
        ).scalar_one_or_none()
        if entry is None:
            return None
        if entry.expires_at is not None and _as_aware_utc(entry.expires_at) < utcnow():
            # Lazy eviction of a stale row.
            self.session.delete(entry)
            self.session.commit()
            return None
        return json.loads(entry.value)

    def set(self, namespace: str, key: str, value: dict, ttl: int | None,
            provider: str | None = None) -> None:
        expires_at = utcnow() + timedelta(seconds=ttl) if ttl and ttl > 0 else None
        entry = self.session.execute(
            select(CacheEntry).where(CacheEntry.namespace == namespace, CacheEntry.key == key)
        ).scalar_one_or_none()
        payload = json.dumps(value)
        if entry is None:
            entry = CacheEntry(namespace=namespace, key=key, value=payload,
                               provider=provider, expires_at=expires_at)
            self.session.add(entry)
        else:
            entry.value = payload
            entry.provider = provider
            entry.expires_at = expires_at
        self.session.commit()

    def get_or_set(self, namespace: str, key: str, ttl: int | None,
                   loader: Callable[[], dict], provider: str | None = None) -> tuple[dict, bool]:
        """Return (value, was_cached). Calls ``loader`` only on a miss."""
        cached = self.get(namespace, key)
        if cached is not None:
            return cached, True
        value = loader()
        self.set(namespace, key, value, ttl, provider=provider)
        return value, False

    def invalidate(self, namespace: str, key: str | None = None) -> int:
        """Delete one key, or the whole namespace when ``key`` is None."""
        stmt = delete(CacheEntry).where(CacheEntry.namespace == namespace)
        if key is not None:
            stmt = stmt.where(CacheEntry.key == key)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def purge_expired(self) -> int:
        result = self.session.execute(
            delete(CacheEntry).where(CacheEntry.expires_at.is_not(None), CacheEntry.expires_at < utcnow())
        )
        self.session.commit()
        return result.rowcount or 0
