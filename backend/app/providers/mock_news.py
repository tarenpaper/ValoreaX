"""Deterministic, offline mock news provider.

Emits **fictional sample** headlines (clearly labeled downstream as provider
'mock') covering a spread of sentiment so the heuristic analyzer and the News
view have realistic, reproducible material with zero network access.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta

from .base import NewsItem, NewsProvider

# (headline template, summary, source, hours_ago). {t} = ticker.
_TEMPLATES = [
    ("{t}: FDA Grants Fast Track Designation for lead candidate",
     "The FDA granted Fast Track designation, a positive step that could speed review.",
     "FDA", 6),
    ("Analyst note: {t} pipeline momentum builds ahead of Phase 3 readout",
     "Coverage highlights an upcoming Phase 3 readout as a key catalyst for the stock.",
     "Bloomberg", 20),
    ("{t} announces strategic partnership to expand oncology franchise",
     "A new collaboration and licensing deal expands the company's oncology reach.",
     "Reuters", 30),
    ("{t} tops quarterly revenue estimates; raises guidance",
     "Quarterly earnings beat estimates and management raised full-year guidance.",
     "Reuters", 52),
    ("Sector rotation pressures large-cap biotech including {t}",
     "Macro headwinds prompted a moderate capital outflow from large-cap biotech names.",
     "Bloomberg", 74),
    ("{t} receives Complete Response Letter for supplemental filing",
     "The FDA issued a CRL, a setback that delays the potential approval timeline.",
     "SEC", 96),
    ("{t} faces generic competition amid looming patent cliff",
     "Analysts flag a patent cliff and generic competition risk for a key product.",
     "Reuters", 130),
    ("{t} files 8-K disclosing updated clinical trial timelines",
     "A routine regulatory filing updated expected trial completion timelines.",
     "SEC", 160),
]


class MockNewsProvider(NewsProvider):
    name = "mock"
    supports_history = True

    def _items(self, ticker: str, anchor: datetime, max_articles: int,
               offset: int = 0) -> list[NewsItem]:
        seed = int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:8], 16)
        items: list[NewsItem] = []
        for i, (headline, summary, source, hours) in enumerate(_TEMPLATES[:max_articles]):
            items.append(NewsItem(
                external_id=f"mock-{ticker.upper()}-{offset}-{i}",
                headline=headline.format(t=ticker.upper()),
                summary=summary,
                source=source,
                url=f"https://example.com/news/{ticker.upper()}/{seed % 100000}-{offset}-{i}",
                published_at=anchor - timedelta(hours=hours + (seed % 5)),
                related=ticker.upper(),
            ))
        return items

    def fetch(self, ticker: str, lookback_days: int = 30, max_articles: int = 40) -> list[NewsItem]:
        return self._items(ticker, datetime.now(UTC), max_articles)

    def fetch_window(self, ticker: str, start: date, end: date,
                     max_articles: int = 40) -> list[NewsItem]:
        """Sample articles dated inside the requested window (deterministic)."""
        anchor = datetime.combine(end, time(12, 0), tzinfo=UTC)
        span_hours = max(1, (end - start).days * 24)
        return [item for item in self._items(ticker, anchor, max_articles, start.toordinal())
                if item.published_at >= anchor - timedelta(hours=span_hours)]
