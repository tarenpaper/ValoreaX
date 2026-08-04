"""Generic TTL cache entry (see app/services/cache_service.py and docs/CACHING.md)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .common import TimestampMixin


class CacheEntry(TimestampMixin, db.Model):
    __tablename__ = "cache_entries"
    __table_args__ = (UniqueConstraint("namespace", "key", name="uq_cache_ns_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True, nullable=False)  # e.g. company_facts
    key: Mapped[str] = mapped_column(String(256), index=True, nullable=False)       # e.g. CIK or ticker
    value: Mapped[str] = mapped_column(Text, nullable=False)                         # JSON text
    provider: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CacheEntry {self.namespace}:{self.key} expires={self.expires_at}>"
