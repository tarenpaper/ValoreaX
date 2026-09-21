"""Ingestion orchestration: provider → raw store → normalize → persist.

Idempotent: re-ingesting a company refreshes its filings and metrics in place.
A cache hit skips rewriting only when this company's filings already reference
the same raw payload and metrics exist, avoiding unnecessary primary-key churn.
Raw provider payloads are stored separately (RawProviderResponse) and de-duplicated
by content hash so normalized values always trace back to exact source bytes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import delete, func, select

from app.models import Company, Filing, FinancialMetric, RawProviderResponse
from app.providers import get_sec_provider
from app.providers.base import CompanyProfile

from .cache_service import CacheService
from .normalization import NormalizationResult, normalize_company_facts


@dataclass
class IngestionResult:
    company: Company
    metric_count: int
    filing_count: int
    warnings: list[str]
    was_cached: bool
    provider: str


def _upsert_company(session, profile: CompanyProfile, provider: str,
                    is_example: bool = False, owner_id: str | None = None) -> Company:
    company = session.execute(
        select(Company).where(Company.ticker == profile.ticker.upper(), Company.owner_id == owner_id)
    ).scalar_one_or_none()
    if company is None:
        company = Company(ticker=profile.ticker.upper(), name=profile.name,
                          is_example=is_example, owner_id=owner_id)
        session.add(company)
    # Refresh classification/profile fields from the provider.
    company.name = profile.name or company.name
    company.cik = profile.cik or company.cik
    company.sector = profile.sector or company.sector
    company.industry = profile.industry or company.industry
    company.exchange = profile.exchange or company.exchange
    company.currency = profile.currency or company.currency
    company.source = provider
    session.flush()
    return company


def _store_raw(session, provider: str, resource_type: str, resource_key: str,
               payload: dict) -> RawProviderResponse:
    text = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(text.encode()).hexdigest()
    existing = session.execute(
        select(RawProviderResponse).where(RawProviderResponse.content_hash == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    raw = RawProviderResponse(
        provider=provider, resource_type=resource_type, resource_key=resource_key,
        content_hash=digest, payload=text,
    )
    session.add(raw)
    session.flush()
    return raw


def _persist(session, company: Company, raw: RawProviderResponse,
             result: NormalizationResult) -> tuple[int, int]:
    # Idempotent refresh: drop prior filings + metrics for this company.
    session.execute(delete(FinancialMetric).where(FinancialMetric.company_id == company.id))
    session.execute(delete(Filing).where(Filing.company_id == company.id))
    session.flush()

    accn_to_filing: dict[str, Filing] = {}
    for accn, fd in result.filings.items():
        filing = Filing(
            company_id=company.id, raw_response_id=raw.id, accession_number=accn,
            form=fd.form, fiscal_year=fd.fiscal_year, fiscal_period=fd.fiscal_period,
            period_end=fd.period_end, filed_date=fd.filed_date, source=raw.provider,
        )
        session.add(filing)
        accn_to_filing[accn] = filing
    session.flush()

    count = 0
    for m in result.metrics:
        filing = accn_to_filing.get(m.accession_number) if m.accession_number else None
        session.add(
            FinancialMetric(
                company_id=company.id,
                filing_id=filing.id if filing else None,
                concept=m.concept, value=m.value, unit=m.unit,
                xbrl_concept=m.xbrl_concept, taxonomy=m.taxonomy,
                accession_number=m.accession_number, form=m.form,
                fiscal_year=m.fiscal_year, fiscal_period=m.fiscal_period,
                period_start=m.period_start, period_end=m.period_end,
                source=m.source, status=m.status.value, confidence=m.confidence,
                quality_note=m.quality_note,
            )
        )
        count += 1
    session.flush()
    return count, len(accn_to_filing)


def _existing_counts(session, company_id: int) -> tuple[int, int]:
    metrics = session.execute(
        select(func.count()).select_from(FinancialMetric).where(
            FinancialMetric.company_id == company_id)
    ).scalar() or 0
    filings = session.execute(
        select(func.count()).select_from(Filing).where(Filing.company_id == company_id)
    ).scalar() or 0
    return metrics, filings


def ingest_company(session, ticker: str, cache: CacheService, config,
                   is_example: bool = False, owner_id: str | None = None) -> IngestionResult:
    """Fetch, normalize, and persist one company's SEC data."""
    provider = get_sec_provider()
    profile = provider.get_profile(ticker)
    company = _upsert_company(session, profile, provider.name, is_example=is_example,
                              owner_id=owner_id)

    ttl = config.get("CACHE_TTL_COMPANY_FACTS", 86_400)
    cache_key = f"{provider.name}:{profile.cik or ticker.upper()}"

    def loader() -> dict:
        return provider.get_company_facts(ticker).payload

    payload, was_cached = cache.get_or_set(
        "company_facts", cache_key, ttl, loader, provider=provider.name
    )
    raw = _store_raw(session, provider.name, "company_facts", cache_key, payload)
    # Provider payloads are shared; each account's stored financials can lag behind.
    persisted_raw_ids = set(session.execute(
        select(Filing.raw_response_id).where(Filing.company_id == company.id).distinct()
    ).scalars())
    # Bump when normalized concepts change so unchanged SEC payloads can be upgraded.
    normalized = CacheService(session)
    normalization_key = str(company.id)
    normalization_version = {"raw_id": raw.id, "version": 2}
    current_normalization = normalized.get("normalization_version", normalization_key)
    if was_cached and persisted_raw_ids == {raw.id} and current_normalization == normalization_version:
        metric_count, filing_count = _existing_counts(session, company.id)
        if metric_count:
            session.commit()
            return IngestionResult(
                company=company, metric_count=metric_count, filing_count=filing_count,
                warnings=[], was_cached=True, provider=provider.name,
            )

    result = normalize_company_facts(payload, source=provider.name)
    metric_count, filing_count = _persist(session, company, raw, result)
    normalized.set("normalization_version", normalization_key, normalization_version, None)
    session.commit()

    return IngestionResult(
        company=company, metric_count=metric_count, filing_count=filing_count,
        warnings=result.warnings, was_cached=was_cached, provider=provider.name,
    )
