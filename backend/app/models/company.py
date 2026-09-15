"""Company profile — the root entity every other record hangs off of."""
from __future__ import annotations

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import TimestampMixin


class Company(TimestampMixin, db.Model):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("owner_id", "ticker", name="uq_companies_owner_ticker"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    # Supabase's verified user UUID. NULL means legacy/CLI data, never exposed by the API.
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True)
    cik: Mapped[str | None] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    exchange: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    description: Mapped[str | None] = mapped_column(String(2048))

    # True for the seeded, clearly-labeled example company (fictional assumptions).
    is_example: Mapped[bool] = mapped_column(Boolean, default=False)

    # Provider that last populated this profile ("mock" | "sec_edgar" | "manual").
    source: Mapped[str] = mapped_column(String(32), default="manual")

    filings = relationship("Filing", back_populates="company", cascade="all, delete-orphan")
    metrics = relationship("FinancialMetric", back_populates="company", cascade="all, delete-orphan")
    catalysts = relationship("CatalystEvent", back_populates="company", cascade="all, delete-orphan")
    prices = relationship("MarketPrice", back_populates="company", cascade="all, delete-orphan")
    signal_runs = relationship("SignalRun", back_populates="company", cascade="all, delete-orphan")
    analyst_consensus = relationship(
        "AnalystConsensus", back_populates="company", uselist=False,
        cascade="all, delete-orphan",
    )
    analyst_ratings = relationship(
        "AnalystRating", back_populates="company", cascade="all, delete-orphan"
    )
    news = relationship("NewsArticle", back_populates="company", cascade="all, delete-orphan")
    product_revenues = relationship("ProductRevenue", back_populates="company",
                                    cascade="all, delete-orphan")
    drug_assets = relationship("DrugAsset", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Company {self.ticker} {self.name!r}>"
