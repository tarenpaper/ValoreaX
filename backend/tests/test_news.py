"""Tests for news ingestion + the composite News view (mock provider, offline)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.models import CatalystEvent, Company, MarketPrice, NewsArticle, RawProviderResponse
from app.providers.mock_news import MockNewsProvider
from app.services.cache_service import CacheService
from app.services.drug_aliases import expand_aliases
from app.services.news_ingestion import ingest_news
from app.services.news_service import _asset_match_terms, build_news_view

CONFIG = {"CACHE_TTL_NEWS": 3600, "NEWS_LOOKBACK_DAYS": 30, "NEWS_MAX_ARTICLES": 40}


def _company(db, ticker="VALX", sector="Healthcare") -> Company:
    company = Company(ticker=ticker, name=f"{ticker} Therapeutics", source="mock", sector=sector)
    db.session.add(company)
    db.session.commit()
    return company


def test_ingest_persists_and_analyzes(db):
    company = _company(db)
    result = ingest_news(db.session, company, MockNewsProvider(), CacheService(db.session), CONFIG)

    assert result.provider == "mock"
    assert result.fetched == result.added > 0
    arts = db.session.execute(
        select(NewsArticle).where(NewsArticle.company_id == company.id)
    ).scalars().all()
    assert len(arts) == result.added
    # Mock supplies no sentiment → heuristic is applied and labeled as such.
    assert all(a.sentiment_method == "heuristic" for a in arts)
    assert {a.sentiment_label for a in arts} & {"bullish", "bearish"}   # spread of sentiment


def test_ingest_is_idempotent(db):
    company = _company(db)
    provider, cache = MockNewsProvider(), CacheService(db.session)
    ingest_news(db.session, company, provider, cache, CONFIG)
    second = ingest_news(db.session, company, provider, cache, CONFIG)
    assert second.added == 0
    assert len(db.session.execute(
        select(NewsArticle).where(NewsArticle.company_id == company.id)
    ).scalars().all()) == 8   # mock has 8 templates, no duplicates


def test_raw_stored(db):
    company = _company(db)
    ingest_news(db.session, company, MockNewsProvider(), CacheService(db.session), CONFIG)
    raw = db.session.execute(
        select(RawProviderResponse).where(RawProviderResponse.resource_type == "news")
    ).scalars().all()
    assert len(raw) == 1


def test_build_news_view_shape(db):
    company = _company(db)
    ingest_news(db.session, company, MockNewsProvider(), CacheService(db.session), CONFIG)
    view = build_news_view(db.session, company)

    assert view["summary"]["total"] == 8
    assert view["summary"]["bullish"] >= 1 and view["summary"]["bearish"] >= 1
    assert len(view["articles"]) == 8
    assert view["articles"][0]["sentiment"]["method"] == "heuristic"
    assert len(view["trending_topics"]) > 0                      # tags extracted from headlines
    assert any(s["sector"] == "Healthcare" for s in view["sector_sentiment"])
    assert "disclaimer" in view


def test_news_api_ingest_and_get(client):
    client.post("/api/v1/companies", json={"ticker": "VALX"})
    ing = client.post("/api/v1/companies/VALX/news/ingest")
    assert ing.status_code == 201
    body = ing.get_json()
    assert body["ingestion"]["provider"] == "mock"
    assert body["ingestion"]["added"] > 0
    assert len(body["articles"]) == body["ingestion"]["added"]
    assert any("heuristic" in w for w in body["ingestion"]["warnings"])

    got = client.get("/api/v1/companies/VALX/news").get_json()
    assert got["summary"]["total"] == body["ingestion"]["added"]
    assert got["articles"][0]["impact"] in {"critical", "high", "medium", "low"}


def test_meta_reports_news_provider(client):
    assert client.get("/api/v1/meta").get_json()["news_provider"] == "mock"


def test_asset_match_terms_splits_combos_and_keeps_specific_indication():
    terms = [t.lower() for t in _asset_match_terms(
        "Talazoparib with enzalutamide", "Metastatic Urothelial Carcinoma")]
    assert "talazoparib" in terms
    assert "enzalutamide" in terms       # combination therapy split into components
    assert "urothelial" in terms         # specific indication keyword kept
    assert "cancer" not in terms and "metastatic" not in terms  # generic words excluded


def _news(db, company_id, ext, headline):
    db.session.add(NewsArticle(
        company_id=company_id, external_id=ext, headline=headline, summary="",
        sentiment_label="neutral", sentiment_score=0.0, sentiment_method="heuristic",
        impact="medium", tags="[]", provider="mock", published_at=datetime.now(UTC),
    ))


def test_matrix_matches_by_drug_component_and_indication(db):
    company = _company(db)
    db.session.add(CatalystEvent(
        company_id=company.id, drug_program="Talazoparib with enzalutamide",
        indication="Metastatic Urothelial Carcinoma", event_type="phase_readout", outcome="pending",
    ))
    _news(db, company.id, "n1", "Enzalutamide combo shows promise in prostate study")   # by component
    _news(db, company.id, "n2", "New readout in urothelial carcinoma patients")          # by indication
    _news(db, company.id, "n3", "Broad market update on healthcare equities")            # no match
    db.session.commit()

    view = build_news_view(db.session, company)
    row = next(r for r in view["catalyst_matrix"] if r["asset"] == "Talazoparib with enzalutamide")
    assert row["news_volume"] == 2
    assert "enzalutamide" in [t.lower() for t in row["match_terms"]]


def test_expand_aliases_is_bidirectional():
    assert "Padcev" in expand_aliases("enfortumab vedotin")
    assert "enfortumab vedotin" in expand_aliases("Padcev")
    assert expand_aliases("some unknown compound") == set()


def test_asset_match_terms_includes_brand_aliases():
    terms = [t.lower() for t in _asset_match_terms("Enfortumab Vedotin", "Urothelial Carcinoma")]
    assert "padcev" in terms                 # brand alias of the generic
    assert "enfortumab vedotin" in terms
    assert "urothelial" in terms


def test_matrix_matches_by_brand_name(db):
    company = _company(db)
    db.session.add(CatalystEvent(
        company_id=company.id, drug_program="Enfortumab Vedotin",
        indication="Metastatic Urothelial Carcinoma", event_type="phase_readout", outcome="pending",
    ))
    _news(db, company.id, "b1", "Padcev shows durable responses in bladder cancer study")
    db.session.commit()

    view = build_news_view(db.session, company)
    row = next(r for r in view["catalyst_matrix"] if r["asset"] == "Enfortumab Vedotin")
    assert row["news_volume"] == 1           # matched via the brand name "Padcev"
    assert "Padcev" in row["match_terms"]


def test_view_surfaces_clinical_articles_first(db):
    company = _company(db)
    db.session.add(CatalystEvent(
        company_id=company.id, drug_program="Enzalutamide", indication="Prostate Cancer",
        event_type="phase_readout", outcome="pending",
    ))
    _news(db, company.id, "c1", "Macro update: markets drift on rate expectations")     # non-clinical
    _news(db, company.id, "c2", "FDA grants Phase 3 trial readout for Enzalutamide")     # clinical + asset
    db.session.commit()

    view = build_news_view(db.session, company)
    assert view["summary"]["clinical"] >= 1
    assert view["articles"][0]["is_clinical"] is True
    assert view["articles"][0]["external_id"] == "c2"       # clinical surfaced to the top


def test_chart_markers_only_include_clinical_news(db):
    company = _company(db)
    today = date.today()
    for i in range(10):
        db.session.add(MarketPrice(company_id=company.id, date=today - timedelta(days=i),
                                   close=100 + i, source="test"))
    _news(db, company.id, "m1", "FDA grants Phase 3 trial readout for the therapy")   # clinical
    _news(db, company.id, "m2", "Broad market rally on macro optimism today")         # non-clinical
    db.session.commit()

    view = build_news_view(db.session, company)
    news_markers = [m for m in view["markers"] if m["kind"] == "news"]
    assert len(news_markers) == 1                            # only the clinical article is marked
    assert news_markers[0]["relevance"] is not None
