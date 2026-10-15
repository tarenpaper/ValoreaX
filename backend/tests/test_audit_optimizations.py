"""Behavior and query-volume regressions for the high-priority backend audit fixes."""
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from statistics import mean

import pytest
from sqlalchemy import event, inspect, select

from app.api.serializers import company_to_dict, metric_to_dict
from app.models import (
    BenchmarkPrice,
    CatalystEvent,
    Company,
    Filing,
    FinancialMetric,
    MarketPrice,
    NewsArticle,
    SignalRun,
)
from app.services import PRIMARY_CONCEPTS
from app.services.derivations import (
    PriceHistory,
    _own_range_reference,
    biotech_profile,
    derive_news_signal_inputs,
    event_window_abnormal_return,
    latest_annual_metrics,
    latest_catalyst_abnormal_return,
    trailing_benchmark_adjusted_return,
)
from app.services.news_service import _sector_sentiment, build_news_view
from app.services.watchlist import build_watchlist

OWNER = "11111111-1111-4111-8111-111111111111"


@contextmanager
def selects(db):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(db.engine, "before_cursor_execute", record)


def company(db, ticker="TEST", owner=OWNER, **kwargs):
    row = Company(ticker=ticker, name=ticker, owner_id=owner, **kwargs)
    db.session.add(row)
    db.session.flush()
    return row


def test_counts_use_one_query_without_loading_relationships(db):
    own = company(db)
    other = company(db, "OTHER")
    for item in (own, other):
        db.session.add(Filing(company_id=item.id, accession_number="test", form="10-K"))
        db.session.add(FinancialMetric(company_id=item.id, concept="revenue", value=100))
        db.session.add(CatalystEvent(company_id=item.id, drug_program="Drug", event_type="other"))
        db.session.add_all([SignalRun(company_id=item.id), SignalRun(company_id=item.id)])
    db.session.flush()
    with selects(db) as queries:
        result = company_to_dict(own, include_counts=True)
    assert result["counts"] == {"filings": 1, "metrics": 1, "catalysts": 1, "signal_runs": 2}
    assert len(queries) == 1
    assert {"filings", "metrics", "catalysts", "signal_runs"} <= inspect(own).unloaded
    empty = company(db, "EMPTY")
    assert set(company_to_dict(empty, include_counts=True)["counts"].values()) == {0}


@pytest.mark.parametrize("years", [(2025, 2024, 2023), (2025, 2023), (None,), ()])
def test_summary_reuses_metrics_and_preserves_undated_records(db, client, years):
    own = company(db)
    for year in years:
        db.session.add(FinancialMetric(company_id=own.id, concept="revenue", value=100,
                                       fiscal_year=year))
    db.session.commit()
    expected_metrics = latest_annual_metrics(db.session, own.id)
    expected_key = {c: metric_to_dict(expected_metrics[c]) for c in PRIMARY_CONCEPTS
                    if c in expected_metrics}
    expected_profile = biotech_profile(db.session, own.id)
    with selects(db) as queries:
        response = client.get("/api/v1/companies/TEST/summary")
    assert response.status_code == 200
    assert response.json["key_metrics"] == expected_key
    assert response.json["biotech_profile"] == expected_profile
    metric_queries = [q for q in queries if "FROM financial_metrics" in q]
    assert len(metric_queries) == (2 if years and years[0] is not None else 3)


def seed_history(db, own, benchmark=True, observations=90):
    start = date(2023, 1, 1)
    for n in range(observations):
        day = start + timedelta(days=n)
        db.session.add(MarketPrice(company_id=own.id, date=day, close=100 + n))
        if benchmark:
            db.session.add(BenchmarkPrice(symbol="XLV", date=day, close=200 + n, source="test"))
    db.session.flush()
    return start


def test_signal_helpers_share_two_history_reads_and_keep_old_observations(db):
    own = company(db)
    start = seed_history(db, own)
    for n in range(3):
        db.session.add(CatalystEvent(company_id=own.id, drug_program="Drug", event_type="other",
                                    actual_date=start - timedelta(days=n + 1), outcome="positive"))
    db.session.flush()
    history = PriceHistory(db.session, own.id, "xlv")
    with selects(db) as queries:
        assert latest_catalyst_abnormal_return(
            db.session, own.id, "XLV", date(2026, 1, 1), price_history=history) is None
        trailing = trailing_benchmark_adjusted_return(
            db.session, own.id, "XLV", price_history=history)
        reference = _own_range_reference(db.session, own.id, 20, "XLV", price_history=history)
        old_event = event_window_abnormal_return(
            db.session, own.id, "XLV", start + timedelta(days=1), price_history=history)
    price_queries = [q for q in queries if "FROM market_prices" in q or "FROM benchmark_prices" in q]
    assert len(price_queries) == 2
    assert trailing == trailing_benchmark_adjusted_return(db.session, own.id, "XLV")
    assert reference == _own_range_reference(db.session, own.id, 20, "XLV")
    assert "90 daily closes" in reference[1]
    assert old_event["start_date"] == "2023-01-01"
    assert old_event == event_window_abnormal_return(db.session, own.id, "XLV", start + timedelta(days=1))


def test_empty_alignment_reuses_raw_prices_and_new_snapshot_sees_changes(db):
    own = company(db)
    seed_history(db, own, benchmark=False)
    history = PriceHistory(db.session, own.id, "XLV")
    with selects(db) as queries:
        assert trailing_benchmark_adjusted_return(db.session, own.id, "XLV", price_history=history) is None
        reference = _own_range_reference(db.session, own.id, 20, "XLV", price_history=history)
    assert len(queries) == 2
    assert reference == (144.5 / 20, "90 daily closes, no benchmark to adjust against")
    row = db.session.execute(select(MarketPrice).where(MarketPrice.company_id == own.id)
                             .order_by(MarketPrice.date.desc()).limit(1)).scalar_one()
    row.close = 1000
    db.session.flush()
    assert PriceHistory(db.session, own.id, "XLV").company_rows != history.company_rows


def test_watchlist_limits_each_company_and_uses_timestamp_then_id(db):
    a = company(db, "AAA")
    b = company(db, "BBB")
    hidden = company(db, "HIDDEN", watched=False)
    other = company(db, "PRIVATE", owner="other")
    start = date(2026, 1, 1)
    for own, size in ((a, 100), (b, 3), (hidden, 10), (other, 10)):
        for n in range(size):
            db.session.add(MarketPrice(company_id=own.id, date=start + timedelta(days=n), close=100 + n))
    latest = datetime(2026, 5, 1, tzinfo=UTC)
    for signal, stamp in (("long", latest), ("short", latest - timedelta(days=10))):
        db.session.add(SignalRun(company_id=a.id, signal=signal, created_at=stamp))
    # Timestamp ties now have an explicit, stable higher-ID winner.
    for signal in ("long", "watchlist"):
        db.session.add(SignalRun(company_id=b.id, signal=signal, created_at=latest))
    db.session.commit()
    db.session.expunge_all()
    with selects(db) as queries:
        result = build_watchlist(db.session, owner_id=OWNER)
    assert len(queries) == 4
    assert [r["ticker"] for r in result] == ["AAA", "BBB"]
    assert result[0]["series"] == list(range(193, 200))
    assert result[0]["change_pct"] == round(199 / 198 - 1, 6)
    assert result[0]["change_7d"] == round(199 / 193 - 1, 6)
    assert result[0]["signal"] == "long"
    assert result[1]["series"] == [100, 101, 102]
    assert result[1]["signal"] == "watchlist"
    assert all("rationale" not in q and "inputs_snapshot" not in q for q in queries)
    assert not any(isinstance(row, (MarketPrice, SignalRun)) for row in db.session.identity_map.values())


def test_sector_grouping_preserves_unknown_rounding_and_owner_boundary(db):
    scores = [0.1005] * 12 + [-0.7, 0.2, 0.8]
    for n, sector in enumerate((None, "", "Unknown")):
        own = company(db, f"U{n}", sector=sector)
        for i, score in enumerate(scores):
            db.session.add(NewsArticle(company_id=own.id, external_id=str(i), headline="News",
                                       sentiment_score=score))
    boundary = company(db, "ROUND", sector="Boundary")
    for i in range(12):
        db.session.add(NewsArticle(company_id=boundary.id, external_id=str(i), headline="News",
                                   sentiment_score=0.1005))
    other = company(db, "OTHER", owner="other", sector="Private")
    db.session.add(NewsArticle(company_id=other.id, external_id="private", headline="News",
                               sentiment_score=1))
    db.session.flush()
    with selects(db) as queries:
        results = _sector_sentiment(db.session, OWNER)
    assert len(queries) == 1 and "GROUP BY" in queries[0]
    assert {row["sector"]: row for row in results} == {
        "Unknown": {"sector": "Unknown", "avg_score": round(mean(scores * 3), 3), "count": 45},
        "Boundary": {"sector": "Boundary", "avg_score": round(mean([0.1005] * 12), 3), "count": 12},
    }
    assert _sector_sentiment(db.session, "empty") == []


def test_news_signal_filters_before_loading_and_includes_full_boundary_days(db):
    own = company(db)
    other = company(db, "OTHER")
    as_of = date(2026, 5, 1)
    end = datetime(2026, 5, 2, tzinfo=UTC)
    cutoff = datetime(2026, 1, 31, tzinfo=UTC)
    samples = [
        (own.id, cutoff, "HIGH", 1.0),
        (own.id, end - timedelta(microseconds=1), "critical", -1.0),
        (own.id, cutoff - timedelta(microseconds=1), "high", 1.0),
        (own.id, end, "high", 1.0),
        (own.id, None, "high", 1.0),
        (own.id, cutoff, "low", 1.0),
        (other.id, cutoff, "high", 1.0),
    ]
    for n, (cid, stamp, impact, score) in enumerate(samples):
        db.session.add(NewsArticle(company_id=cid, external_id=str(n), headline="News",
                                   published_at=stamp, impact=impact, sentiment_score=score,
                                   sentiment_method="provider"))
    db.session.commit()
    cid = own.id
    db.session.expunge_all()
    loaded = []

    def record(article, context):
        loaded.append(article.external_id)

    event.listen(NewsArticle, "load", record)
    try:
        result = derive_news_signal_inputs(db.session, cid, as_of)
    finally:
        event.remove(NewsArticle, "load", record)
    assert loaded == ["0", "1"]
    assert result == {"news_sentiment": -0.3333, "news_article_count": 2}


def test_news_view_limits_chart_and_loads_catalysts_once(db):
    own = company(db)
    start = seed_history(db, own, benchmark=False)
    db.session.add(CatalystEvent(company_id=own.id, drug_program="Drug", event_type="other",
                                expected_date=start + timedelta(days=89)))
    db.session.flush()
    with selects(db) as queries:
        result = build_news_view(db.session, own)
    assert len([q for q in queries if "FROM catalyst_events" in q]) == 1
    assert len(result["price_series"]) == 40
    assert result["price_series"][0] == {"date": (start + timedelta(days=50)).isoformat(), "close": 150}
    assert result["price_series"][-1]["close"] == 189
    assert len(result["markers"]) == 1
    assert result["markers"][0]["kind"] == "catalyst"


def test_navigation_updates_benchmark_once_per_request(db, client, monkeypatch):
    from app.providers import PricePoint

    company(db, "AAA")
    company(db, "BBB")
    db.session.commit()
    calls = []

    class Market:
        name = "audit"

        def get_prices(self, ticker, lookback_days):
            calls.append(ticker)
            return [PricePoint(date=date(2026, 1, 1), close=100)]

    monkeypatch.setattr("app.api.v1.prices.get_market_provider", lambda: Market())
    for _ in range(2):
        with selects(db) as queries:
            response = client.post("/api/v1/navigation/refresh", json={"view": "watchlist"})
        assert response.status_code == 200 and response.json["warnings"] == []
        assert len([q for q in queries if "FROM benchmark_prices" in q]) == 1
        prices = [r for r in response.json["results"] if r["source"] == "audit"]
        assert len(prices) == 2 and all(r["benchmark_synced"] == 1 for r in prices)
    assert calls == ["AAA", "XLV", "BBB"]
    # A standalone sync still checks the benchmark independently.
    with selects(db) as queries:
        assert client.post("/api/v1/companies/AAA/prices/sync").status_code == 201
    assert len([q for q in queries if "FROM benchmark_prices" in q]) == 1


def test_navigation_retries_failed_benchmark_for_next_company(db, client, monkeypatch):
    from app.providers import PricePoint, ProviderError

    company(db, "AAA")
    company(db, "BBB")
    db.session.commit()
    calls = []

    class Market:
        name = "audit_retry"

        def get_prices(self, ticker, lookback_days):
            calls.append(ticker)
            if ticker == "XLV" and calls.count("XLV") == 1:
                raise ProviderError("Temporary failure")
            return [PricePoint(date=date(2026, 1, 1), close=100)]

    monkeypatch.setattr("app.api.v1.prices.get_market_provider", lambda: Market())
    response = client.post("/api/v1/navigation/refresh", json={"view": "watchlist"})
    assert response.status_code == 200
    assert len(response.json["warnings"]) == 1
    assert "AAA prices" in response.json["warnings"][0]
    assert calls == ["AAA", "XLV", "BBB", "XLV"]
    prices = [r for r in response.json["results"] if r["source"] == "audit_retry"]
    assert len(prices) == 1 and prices[0]["ticker"] == "BBB"
