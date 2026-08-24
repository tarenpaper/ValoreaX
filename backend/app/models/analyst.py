"""Analyst coverage: a per-company consensus snapshot plus individual institution ratings.

Consensus (rating distribution + price targets) drives the signal engine; the
individual `AnalystRating` rows preserve *which institutions* said what, so the
UI can show coverage from different firms rather than an opaque average.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import TimestampMixin


class AnalystConsensus(TimestampMixin, db.Model):
    """One upserted consensus snapshot per company."""

    __tablename__ = "analyst_consensus"
    __table_args__ = (UniqueConstraint("company_id", name="uq_analyst_consensus_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    # Rating distribution (counts of covering analysts by bucket).
    strong_buy: Mapped[int] = mapped_column(Integer, default=0)
    buy: Mapped[int] = mapped_column(Integer, default=0)
    hold: Mapped[int] = mapped_column(Integer, default=0)
    sell: Mapped[int] = mapped_column(Integer, default=0)
    strong_sell: Mapped[int] = mapped_column(Integer, default=0)
    consensus_label: Mapped[str | None] = mapped_column(String(16))  # Strong Buy .. Strong Sell

    # Price targets and the reference price used for implied upside.
    target_high: Mapped[float | None] = mapped_column(Float)
    target_low: Mapped[float | None] = mapped_column(Float)
    target_consensus: Mapped[float | None] = mapped_column(Float)
    target_median: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)

    analyst_count: Mapped[int] = mapped_column(Integer, default=0)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), default="mock")

    company = relationship("Company", back_populates="analyst_consensus")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnalystConsensus {self.consensus_label} target={self.target_consensus}>"


class AnalystRating(TimestampMixin, db.Model):
    """One institution's view (grade and/or price target) on a company."""

    __tablename__ = "analyst_ratings"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    institution: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "Morgan Stanley"
    grade: Mapped[str | None] = mapped_column(String(32))                  # e.g. "Overweight"
    action: Mapped[str | None] = mapped_column(String(16))                 # upgrade|downgrade|initiate|maintain|target
    price_target: Mapped[float | None] = mapped_column(Float)
    rating_date: Mapped[date | None] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(32), default="mock")
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)  # dedupe key

    company = relationship("Company", back_populates="analyst_ratings")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnalystRating {self.institution} {self.grade} target={self.price_target}>"
