"""Analyst-coverage ingestion: provider → cache → raw store → upsert.

Persists one `AnalystConsensus` snapshot per company (upserted) plus a fresh set
of per-institution `AnalystRating` rows. The raw fetch is stored verbatim in
RawProviderResponse (resource_type="analyst") for provenance. Nothing is
fabricated — missing fields stay null and are surfaced as warnings.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import delete, select

from app.models import AnalystConsensus, AnalystRating, RawProviderResponse
from app.providers.base import (
    AnalystConsensusData,
    AnalystData,
    AnalystDataProvider,
    AnalystRatingRecord,
)

from .cache_service import CacheService


@dataclass
class AnalystIngestionResult:
    provider: str
    analyst_count: int
    rating_rows: int
    consensus_label: str | None
    target_consensus: float | None
    implied_upside: float | None
    was_cached: bool
    warnings: list[str]


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def implied_upside(target_consensus: float | None, current_price: float | None) -> float | None:
    """Fractional upside of the consensus target vs. the current price."""
    if not target_consensus or not current_price or current_price <= 0:
        return None
    return round(target_consensus / current_price - 1.0, 6)


def _serialize(data: AnalystData) -> dict:
    c = data.consensus
    return {
        "consensus": {
            "strong_buy": c.strong_buy, "buy": c.buy, "hold": c.hold,
            "sell": c.sell, "strong_sell": c.strong_sell,
            "consensus_label": c.consensus_label,
            "target_high": c.target_high, "target_low": c.target_low,
            "target_consensus": c.target_consensus, "target_median": c.target_median,
            "current_price": c.current_price, "analyst_count": c.analyst_count,
            "as_of_date": _iso(c.as_of_date),
        },
        "ratings": [
            {
                "institution": r.institution, "grade": r.grade, "action": r.action,
                "price_target": r.price_target, "rating_date": _iso(r.rating_date),
                "external_id": r.external_id,
            }
            for r in data.ratings
        ],
        "warnings": data.warnings,
    }


def _deserialize(payload: dict) -> AnalystData:
    c = payload.get("consensus", {})
    consensus = AnalystConsensusData(
        strong_buy=c.get("strong_buy", 0), buy=c.get("buy", 0), hold=c.get("hold", 0),
        sell=c.get("sell", 0), strong_sell=c.get("strong_sell", 0),
        consensus_label=c.get("consensus_label"),
        target_high=c.get("target_high"), target_low=c.get("target_low"),
        target_consensus=c.get("target_consensus"), target_median=c.get("target_median"),
        current_price=c.get("current_price"), analyst_count=c.get("analyst_count", 0),
        as_of_date=_parse_date(c.get("as_of_date")),
    )
    ratings = [
        AnalystRatingRecord(
            institution=r["institution"], grade=r.get("grade"), action=r.get("action"),
            price_target=r.get("price_target"), rating_date=_parse_date(r.get("rating_date")),
            external_id=r.get("external_id"),
        )
        for r in payload.get("ratings", [])
    ]
    return AnalystData(consensus=consensus, ratings=ratings, warnings=payload.get("warnings", []))


def _is_meaningful(payload: dict) -> bool:
    """True if a fetched payload actually carries coverage worth caching."""
    c = payload.get("consensus", {})
    return bool(
        c.get("analyst_count") or c.get("target_consensus")
        or c.get("current_price") or payload.get("ratings")
    )


def _store_raw(session, provider: str, resource_key: str, payload: dict) -> None:
    text = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(text.encode()).hexdigest()
    if session.execute(
        select(RawProviderResponse).where(RawProviderResponse.content_hash == digest)
    ).scalar_one_or_none() is not None:
        return
    session.add(RawProviderResponse(
        provider=provider, resource_type="analyst", resource_key=resource_key,
        content_hash=digest, payload=text,
    ))
    session.flush()


def ingest_analyst_data(session, company, provider: AnalystDataProvider, cache: CacheService,
                        config) -> AnalystIngestionResult:
    """Fetch and upsert analyst coverage for one company."""
    ttl = config.get("CACHE_TTL_ANALYST", 21_600)
    cache_key = f"{provider.name}:{company.ticker}"

    # Only serve/keep meaningful pulls: an empty result (e.g. a transient upstream
    # gap) is never cached, and a previously-cached empty one is refetched.
    cached = cache.get("analyst", cache_key)
    if cached is not None and _is_meaningful(cached):
        payload, was_cached = cached, True
    else:
        payload = _serialize(provider.fetch(company.ticker))
        was_cached = False
        if _is_meaningful(payload):
            cache.set("analyst", cache_key, payload, ttl, provider=provider.name)

    _store_raw(session, provider.name, cache_key, payload)
    data = _deserialize(payload)
    c = data.consensus

    # Upsert the single consensus snapshot.
    row = session.execute(
        select(AnalystConsensus).where(AnalystConsensus.company_id == company.id)
    ).scalar_one_or_none()
    if row is None:
        row = AnalystConsensus(company_id=company.id)
        session.add(row)
    row.strong_buy, row.buy, row.hold = c.strong_buy, c.buy, c.hold
    row.sell, row.strong_sell = c.sell, c.strong_sell
    row.consensus_label = c.consensus_label
    row.target_high, row.target_low = c.target_high, c.target_low
    row.target_consensus, row.target_median = c.target_consensus, c.target_median
    row.current_price, row.analyst_count = c.current_price, c.analyst_count
    row.as_of_date, row.source = c.as_of_date, provider.name

    # Replace the per-institution rows (a fresh snapshot each pull).
    session.execute(delete(AnalystRating).where(AnalystRating.company_id == company.id))
    for r in data.ratings:
        session.add(AnalystRating(
            company_id=company.id, institution=r.institution, grade=r.grade, action=r.action,
            price_target=r.price_target, rating_date=r.rating_date,
            source=provider.name, external_id=r.external_id,
        ))
    session.commit()

    return AnalystIngestionResult(
        provider=provider.name, analyst_count=c.analyst_count, rating_rows=len(data.ratings),
        consensus_label=c.consensus_label, target_consensus=c.target_consensus,
        implied_upside=implied_upside(c.target_consensus, c.current_price),
        was_cached=was_cached, warnings=data.warnings,
    )
