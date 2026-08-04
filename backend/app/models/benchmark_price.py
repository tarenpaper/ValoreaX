"""Benchmark price history used for market-adjusted returns."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .common import TimestampMixin


class BenchmarkPrice(TimestampMixin, db.Model):
    """A reusable market or sector benchmark series, stored independently of issuers."""

    __tablename__ = "benchmark_prices"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_benchmark_price_symbol_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(48), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BenchmarkPrice {self.symbol} {self.date} close={self.close}>"
