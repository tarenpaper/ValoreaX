"""Persisted signal-engine runs.

Each run stores an immutable snapshot of its inputs plus the human-readable
rationale, so results are fully reproducible and auditable. `as_of_date` records
the point in time the snapshot represents — the anchor that lets future versions
compare a pre-event signal against later analyst views without look-ahead bias.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import SignalType, TimestampMixin


class SignalRun(TimestampMixin, db.Model):
    __tablename__ = "signal_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    signal: Mapped[str] = mapped_column(String(16), default=SignalType.WATCHLIST.value)
    score: Mapped[float] = mapped_column(Float, default=0.0)         # -100..100
    confidence: Mapped[float] = mapped_column(Float, default=0.0)    # 0..1

    # Point in time the input snapshot represents (guards against look-ahead bias).
    as_of_date: Mapped[date | None] = mapped_column(Date, index=True)

    engine_version: Mapped[str] = mapped_column(String(16), default="v1")

    # JSON blobs stored as text for portability across SQLite/Postgres.
    inputs_snapshot: Mapped[str | None] = mapped_column(Text)  # exact inputs used
    rationale: Mapped[str | None] = mapped_column(Text)        # ordered component contributions

    company = relationship("Company", back_populates="signal_runs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SignalRun {self.signal} score={self.score:.1f} conf={self.confidence:.2f}>"
