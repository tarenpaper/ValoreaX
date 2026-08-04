"""Normalized financial values, each retaining full source provenance.

One row = one normalized concept for one fiscal period, with the metadata a
reviewer needs to trust (or challenge) it: the originating XBRL concept, the
filing accession number, form, period, unit, and an extraction status/confidence.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import MetricStatus, TimestampMixin


class FinancialMetric(TimestampMixin, db.Model):
    __tablename__ = "financial_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"), index=True)

    # Normalized concept name in our own vocabulary (revenue, operating_income, ...).
    concept: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), default="USD")

    # --- Source provenance -------------------------------------------------
    xbrl_concept: Mapped[str | None] = mapped_column(String(128))  # e.g. OperatingIncomeLoss
    taxonomy: Mapped[str | None] = mapped_column(String(16))       # us-gaap | dei | derived
    accession_number: Mapped[str | None] = mapped_column(String(32))
    form: Mapped[str | None] = mapped_column(String(16))
    fiscal_year: Mapped[int | None] = mapped_column()
    fiscal_period: Mapped[str | None] = mapped_column(String(4))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # mock | sec_edgar | derived

    # --- Data quality ------------------------------------------------------
    status: Mapped[str] = mapped_column(String(16), default=MetricStatus.REPORTED.value)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)  # 0..1
    quality_note: Mapped[str | None] = mapped_column(Text)

    company = relationship("Company", back_populates="metrics")
    filing = relationship("Filing", back_populates="metrics")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FinancialMetric {self.concept}={self.value} {self.fiscal_year}{self.fiscal_period} [{self.status}]>"
