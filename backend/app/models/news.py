"""News articles with (labeled) sentiment, one row per company/article.

Sentiment is either taken from the provider or computed by a transparent keyword
heuristic — `sentiment_method` records which, so nothing is passed off as a
verified analyst view. Tags/impact are likewise derived and clearly heuristic.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import TimestampMixin


class NewsArticle(TimestampMixin, db.Model):
    __tablename__ = "news_articles"
    __table_args__ = (UniqueConstraint("company_id", "external_id", name="uq_news_company_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    external_id: Mapped[str] = mapped_column(String(64), index=True)  # provider id or url hash
    headline: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(64))            # publisher (Reuters, ...)
    url: Mapped[str | None] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    related: Mapped[str | None] = mapped_column(String(128))          # related tickers, comma-sep

    # --- Derived, clearly labeled ------------------------------------------
    sentiment_label: Mapped[str] = mapped_column(String(12), default="neutral")  # bullish/bearish/neutral
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)           # -1..+1
    sentiment_method: Mapped[str] = mapped_column(String(12), default="heuristic")  # provider|heuristic
    impact: Mapped[str] = mapped_column(String(12), default="medium")            # critical/high/medium/low
    tags: Mapped[str | None] = mapped_column(Text)                                # JSON list of topic tags

    provider: Mapped[str] = mapped_column(String(32), default="mock")

    company = relationship("Company", back_populates="news")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NewsArticle {self.sentiment_label} {self.headline[:40]!r}>"
