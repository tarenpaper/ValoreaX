"""Live Finnhub company-news adapter — free tier, API key required.

Uses the public `/company-news` endpoint:

    GET https://finnhub.io/api/v1/company-news?symbol=PFE&from=YYYY-MM-DD&to=YYYY-MM-DD&token=KEY

Finnhub's free company-news does not carry per-article sentiment, so `NewsItem`
sentiment is left None here and computed by the transparent heuristic downstream
(labeled as such). The pure `_map_article` helper holds the mapping for tests.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import requests

from .base import NewsItem, NewsProvider, ProviderError


def _map_article(row: dict) -> NewsItem | None:
    headline = row.get("headline")
    if not headline:
        return None
    ts = row.get("datetime")
    published = datetime.fromtimestamp(ts, tz=UTC) if isinstance(ts, (int, float)) and ts else None
    ext = row.get("id")
    external_id = str(ext) if ext else (row.get("url") or headline)[:64]
    return NewsItem(
        external_id=external_id,
        headline=str(headline)[:512],
        summary=row.get("summary") or None,
        source=row.get("source") or None,
        url=row.get("url") or None,
        published_at=published,
        related=row.get("related") or None,
        # Finnhub free company-news has no per-article sentiment → heuristic downstream.
        sentiment_label=None,
        sentiment_score=None,
    )


class FinnhubNewsProvider(NewsProvider):
    name = "finnhub"

    def __init__(self, api_key: str, base_url: str = "https://finnhub.io/api/v1", timeout: int = 20) -> None:
        if not api_key:
            raise ProviderError("FINNHUB_API_KEY is required when NEWS_PROVIDER=finnhub.")
        self._key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    def fetch(self, ticker: str, lookback_days: int = 30, max_articles: int = 40) -> list[NewsItem]:
        today = date.today()
        params = {
            "symbol": ticker.upper(),
            "from": (today - timedelta(days=lookback_days)).isoformat(),
            "to": today.isoformat(),
            "token": self._key,
        }
        try:
            resp = self._session.get(f"{self._base_url}/company-news", params=params, timeout=self._timeout)
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"Finnhub request failed: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"Finnhub returned HTTP {resp.status_code} for {ticker!r}.")
        try:
            data = resp.json()
        except ValueError as exc:  # pragma: no cover
            raise ProviderError("Finnhub returned non-JSON.") from exc
        if not isinstance(data, list):
            return []
        items: list[NewsItem] = []
        for row in data[:max_articles]:
            item = _map_article(row)
            if item is not None:
                items.append(item)
        return items
