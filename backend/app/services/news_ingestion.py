"""News ingestion: provider → cache → raw store → analyze → upsert.

Each article's sentiment is taken from the provider when present, otherwise
computed by the transparent keyword heuristic — `sentiment_method` records which.
Impact tier and topic tags are always heuristic. Idempotent per (company, article).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.models import NewsArticle, RawProviderResponse
from app.providers.base import NewsItem, NewsProvider

from .cache_service import CacheService
from .news_analysis import classify_impact, extract_tags, heuristic_sentiment


@dataclass
class NewsIngestionResult:
    provider: str
    fetched: int
    added: int
    skipped: int
    was_cached: bool
    warnings: list[str]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _serialize(items: list[NewsItem]) -> dict:
    return {"items": [
        {
            "external_id": i.external_id, "headline": i.headline, "summary": i.summary,
            "source": i.source, "url": i.url, "published_at": _iso(i.published_at),
            "related": i.related, "sentiment_label": i.sentiment_label,
            "sentiment_score": i.sentiment_score,
        }
        for i in items
    ]}


def _deserialize(payload: dict) -> list[NewsItem]:
    return [
        NewsItem(
            external_id=d["external_id"], headline=d["headline"], summary=d.get("summary"),
            source=d.get("source"), url=d.get("url"), published_at=_parse_dt(d.get("published_at")),
            related=d.get("related"), sentiment_label=d.get("sentiment_label"),
            sentiment_score=d.get("sentiment_score"),
        )
        for d in payload.get("items", [])
    ]


def _store_raw(session, provider: str, resource_key: str, payload: dict) -> None:
    text = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(text.encode()).hexdigest()
    if session.execute(
        select(RawProviderResponse).where(RawProviderResponse.content_hash == digest)
    ).scalar_one_or_none() is not None:
        return
    session.add(RawProviderResponse(
        provider=provider, resource_type="news", resource_key=resource_key,
        content_hash=digest, payload=text,
    ))
    session.flush()


def ingest_news(session, company, provider: NewsProvider, cache: CacheService,
                config) -> NewsIngestionResult:
    """Fetch, analyze, and upsert news for one company."""
    ttl = config.get("CACHE_TTL_NEWS", 3_600)
    lookback = config.get("NEWS_LOOKBACK_DAYS", 30)
    max_articles = config.get("NEWS_MAX_ARTICLES", 40)
    cache_key = f"{provider.name}:{company.ticker}"

    cached = cache.get("news", cache_key)
    if cached is not None and cached.get("items"):
        payload, was_cached = cached, True
    else:
        payload = _serialize(provider.fetch(company.ticker, lookback_days=lookback, max_articles=max_articles))
        was_cached = False
        if payload.get("items"):
            cache.set("news", cache_key, payload, ttl, provider=provider.name)

    _store_raw(session, provider.name, cache_key, payload)
    items = _deserialize(payload)

    existing = set(
        session.execute(
            select(NewsArticle.external_id).where(NewsArticle.company_id == company.id)
        ).scalars().all()
    )

    added = skipped = 0
    for item in items:
        if not item.external_id or item.external_id in existing:
            skipped += 1
            continue
        text = f"{item.headline} {item.summary or ''}"
        if item.sentiment_label is not None:
            label, score, method = item.sentiment_label, item.sentiment_score or 0.0, "provider"
        else:
            label, score = heuristic_sentiment(text)
            method = "heuristic"
        session.add(NewsArticle(
            company_id=company.id, external_id=item.external_id, headline=item.headline,
            summary=item.summary, source=item.source, url=item.url, published_at=item.published_at,
            related=item.related, sentiment_label=label, sentiment_score=round(score, 3),
            sentiment_method=method, impact=classify_impact(item.source, text),
            tags=json.dumps(extract_tags(text)), provider=provider.name,
        ))
        existing.add(item.external_id)
        added += 1

    session.commit()

    warnings: list[str] = []
    if items:
        warnings.append(
            "Sentiment/impact/tags are a transparent keyword heuristic where the provider "
            "supplies none — not verified analyst sentiment."
        )
    if provider.name == "mock" and items:
        warnings.append("Provider is 'mock' — illustrative SAMPLE headlines, not real news.")

    return NewsIngestionResult(
        provider=provider.name, fetched=len(items), added=added, skipped=skipped,
        was_cached=was_cached, warnings=warnings,
    )
