"""Filing metadata and raw provider payloads.

`RawProviderResponse` deliberately stores the *unmodified* provider response so
that normalized values (FinancialMetric) can always be traced back to, and
re-derived from, the exact bytes we received. Raw and normalized data never
share a table.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import TimestampMixin


class RawProviderResponse(TimestampMixin, db.Model):
    """Immutable raw payload as returned by a data provider (JSON stored as text)."""

    __tablename__ = "raw_provider_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)          # mock | sec_edgar
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)     # company_facts | submissions
    resource_key: Mapped[str] = mapped_column(String(64), index=True)          # e.g. CIK or ticker
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)   # sha256 for dedupe
    payload: Mapped[str] = mapped_column(Text, nullable=False)                  # raw JSON text

    filings = relationship("Filing", back_populates="raw_response")


class Filing(TimestampMixin, db.Model):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    raw_response_id: Mapped[int | None] = mapped_column(ForeignKey("raw_provider_responses.id"))

    accession_number: Mapped[str] = mapped_column(String(32), index=True)
    form: Mapped[str] = mapped_column(String(16))               # 10-K, 10-Q, 8-K, ...
    fiscal_year: Mapped[int | None] = mapped_column()
    fiscal_period: Mapped[str | None] = mapped_column(String(4))  # FY, Q1..Q4
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    filed_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), default="manual")

    company = relationship("Company", back_populates="filings")
    raw_response = relationship("RawProviderResponse", back_populates="filings")
    metrics = relationship("FinancialMetric", back_populates="filing")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Filing {self.form} {self.fiscal_year}{self.fiscal_period} accn={self.accession_number}>"
