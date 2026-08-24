"""Clinical / FDA catalyst events (manually entered in the MVP)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import CatalystOutcome, TimestampMixin


class CatalystEvent(TimestampMixin, db.Model):
    __tablename__ = "catalyst_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    drug_program: Mapped[str] = mapped_column(String(256), nullable=False)
    indication: Mapped[str | None] = mapped_column(String(256))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)   # see CatalystEventType
    trial_phase: Mapped[str | None] = mapped_column(String(32))           # Preclinical/Phase 1/2/3/Filed/Approved
    expected_date: Mapped[date | None] = mapped_column(Date, index=True)
    actual_date: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str] = mapped_column(String(16), default=CatalystOutcome.PENDING.value)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    notes: Mapped[str | None] = mapped_column(Text)

    # Provenance: manual entry vs. an automated adapter (e.g. clinicaltrials).
    source: Mapped[str] = mapped_column(String(32), default="manual")
    # External identifier for idempotent auto-ingest (e.g. a ClinicalTrials.gov NCT id).
    # NULL for manually-entered events, which auto-ingest never touches.
    external_id: Mapped[str | None] = mapped_column(String(32), index=True)

    company = relationship("Company", back_populates="catalysts")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CatalystEvent {self.drug_program} {self.event_type} {self.expected_date}>"
