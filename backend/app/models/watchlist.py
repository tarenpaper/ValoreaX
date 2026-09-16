"""A named basket of tickers whose name is an anagram of their initials.

Members are stored as an ordered JSON list rather than a join table: a basket holds at most
seven, the order is display state, and nothing queries which baskets contain a ticker.
"""
from __future__ import annotations

import json

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .common import TimestampMixin


class WatchlistBasket(TimestampMixin, db.Model):
    __tablename__ = "watchlist_baskets"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_basket_owner_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(32))
    tickers: Mapped[str] = mapped_column(Text)

    def member_tickers(self) -> list[str]:
        try:
            values = json.loads(self.tickers or "[]")
        except ValueError:
            return []
        return [str(t).upper() for t in values if t]

    def set_members(self, tickers: list[str]) -> None:
        self.tickers = json.dumps([str(t).upper() for t in tickers])

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<WatchlistBasket {self.name} {self.member_tickers()}>"
