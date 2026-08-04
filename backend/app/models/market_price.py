"""Historical market prices (used for abnormal-return inputs to the signal engine)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import TimestampMixin


class MarketPrice(TimestampMixin, db.Model):
    __tablename__ = "market_prices"
    __table_args__ = (UniqueConstraint("company_id", "date", name="uq_price_company_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="mock")

    company = relationship("Company", back_populates="prices")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MarketPrice {self.date} close={self.close}>"
