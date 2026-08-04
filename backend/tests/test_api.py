"""Integration tests for the /api/v1 endpoints (mock provider)."""
from __future__ import annotations

import pytest

V1 = "/api/v1"


@pytest.fixture()
def ingested(client):
    """Ingest the sample VALX company and return its payload."""
    resp = client.post(f"{V1}/companies", json={"ticker": "VALX"})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def test_health_and_meta(client):
    assert client.get(f"{V1}/health").get_json()["status"] == "ok"
    meta = client.get(f"{V1}/meta").get_json()
    assert meta["provider"] == "mock"
    assert "VALX" in meta["available_mock_tickers"]
    assert "not investment advice" in meta["disclaimer"].lower()


def test_ingest_company(ingested):
    assert ingested["company"]["ticker"] == "VALX"
    assert ingested["company"]["name"].endswith("(SAMPLE)")
    assert ingested["ingestion"]["metric_count"] > 0


def test_unknown_ticker_returns_404(client):
    resp = client.post(f"{V1}/companies", json={"ticker": "ZZZZ"})
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_ingest_validation_error(client):
    resp = client.post(f"{V1}/companies", json={})
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "validation_error"


def test_company_summary_has_key_metrics(client, ingested):
    resp = client.get(f"{V1}/companies/VALX/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["latest_fiscal_year"] == 2025
    for concept in ("revenue", "cash", "total_debt", "shares_outstanding", "ebitda"):
        assert concept in body["key_metrics"]
    # Provenance + quality present on each metric.
    rev = body["key_metrics"]["revenue"]
    assert rev["provenance"]["xbrl_concept"] == "Revenues"
    assert rev["quality"]["status"] == "reported"


def test_metrics_and_filings_endpoints(client, ingested):
    metrics = client.get(f"{V1}/companies/VALX/metrics").get_json()
    assert metrics["count"] > 0
    filtered = client.get(f"{V1}/companies/VALX/metrics?concept=revenue").get_json()
    assert all(m["concept"] == "revenue" for m in filtered["metrics"])
    filings = client.get(f"{V1}/companies/VALX/filings").get_json()
    assert filings["count"] >= 1


def test_valuation_endpoint(client, ingested):
    resp = client.post(f"{V1}/companies/VALX/valuation", json={
        "assumptions": {"revenue_growth": 0.15, "operating_margin": 0.12, "wacc": 0.11},
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["scenarios"]) == {"base", "bull", "bear"}
    assert body["inputs"]["sources"]["base_revenue"] == "sec"
    assert body["sensitivity"] is not None
    for name in ("base", "bull", "bear"):
        assert "implied_share_price" in body["scenarios"][name]


def test_valuation_invalid_assumptions_returns_422(client, ingested):
    resp = client.post(f"{V1}/companies/VALX/valuation", json={
        "assumptions": {"revenue_growth": 0.15, "operating_margin": 0.12,
                        "wacc": 0.02, "terminal_growth": 0.03},  # wacc <= g
    })
    assert resp.status_code == 422


def test_catalyst_crud(client, ingested):
    # Create
    created = client.post(f"{V1}/companies/VALX/catalysts", json={
        "drug_program": "VLX-999", "event_type": "pdufa",
        "indication": "Test indication", "expected_date": "2026-12-01", "outcome": "pending",
    })
    assert created.status_code == 201
    cid = created.get_json()["id"]

    # List
    listing = client.get(f"{V1}/companies/VALX/catalysts").get_json()
    assert listing["count"] == 1

    # Get
    assert client.get(f"{V1}/catalysts/{cid}").status_code == 200

    # Patch
    patched = client.patch(f"{V1}/catalysts/{cid}", json={"outcome": "positive"})
    assert patched.get_json()["outcome"] == "positive"

    # Delete
    assert client.delete(f"{V1}/catalysts/{cid}").get_json()["deleted"] is True
    assert client.get(f"{V1}/catalysts/{cid}").status_code == 404


def test_catalyst_invalid_outcome_rejected(client, ingested):
    resp = client.post(f"{V1}/companies/VALX/catalysts", json={
        "drug_program": "X", "event_type": "pdufa", "outcome": "moon",
    })
    assert resp.status_code == 422


def test_prices_sync_and_signal_flow(client, ingested):
    synced = client.post(f"{V1}/companies/VALX/prices/sync")
    assert synced.status_code == 201
    assert synced.get_json()["synced"] > 0

    sig = client.post(f"{V1}/companies/VALX/signals", json={
        "valuation_upside": 0.3, "manual_confidence": 0.8,
    })
    assert sig.status_code == 201
    body = sig.get_json()
    assert body["signal"] in {"long", "short", "watchlist"}
    assert body["persisted_run_id"] is not None
    assert body["rationale"]

    history = client.get(f"{V1}/companies/VALX/signals").get_json()
    assert history["count"] == 1


def test_backtest_reports_no_fabricated_result_without_data(client, ingested):
    # A fresh signal (as_of today) with no future resolved catalysts -> null rate.
    client.post(f"{V1}/companies/VALX/signals", json={"valuation_upside": 0.3, "manual_confidence": 0.8})
    bt = client.get(f"{V1}/companies/VALX/signals/backtest").get_json()
    assert bt["directional_agreement_rate"] is None
    assert bt["evaluated"] == 0
