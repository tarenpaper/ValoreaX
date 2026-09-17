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


def test_company_list_omits_relationship_counts(client, ingested):
    listing = client.get(f"{V1}/companies").get_json()["companies"]
    assert listing[0]["ticker"] == "VALX"
    assert "counts" not in listing[0]
    detail = client.get(f"{V1}/companies/VALX").get_json()
    assert detail["counts"]["metrics"] > 0
    assert detail["counts"]["filings"] >= 1


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


def test_company_summary_includes_stage_aware_biotech_profile(app, client, ingested):
    profile = client.get(f"{V1}/companies/VALX/summary").get_json()["biotech_profile"]
    # VALX FY2025 has positive operating cash flow.
    assert profile["stage"] == "cash_generative"
    assert profile["fiscal_year"] == 2025
    assert len(profile["headline"]) == 6
    assert set(profile["headline"]) <= set(profile["figures"])

    figures = profile["figures"]
    assert figures["liquidity"]["value"] == 1240e6 + 700e6 + 320e6
    assert figures["runway_quarters"]["status"] == "not_meaningful"
    assert figures["dilution_yoy"]["value"] == pytest.approx(240e6 / 226e6 - 1)

    # The signal engine's runway input shares the dashboard's definition.
    from app.extensions import db
    from app.services.derivations import estimate_cash_runway_quarters
    with app.app_context():
        assert estimate_cash_runway_quarters(db.session, ingested["company"]["id"]) is None


def test_metrics_and_filings_endpoints(client, ingested):
    metrics = client.get(f"{V1}/companies/VALX/metrics").get_json()
    assert metrics["count"] > 0
    filtered = client.get(f"{V1}/companies/VALX/metrics?concept=revenue").get_json()
    assert all(m["concept"] == "revenue" for m in filtered["metrics"])
    filings = client.get(f"{V1}/companies/VALX/filings").get_json()
    assert filings["count"] >= 1


def test_valuation_reports_no_value_when_no_drugs_are_modelled(client, ingested):
    """The sample company has no filing to model drugs from, so nothing is invented."""
    resp = client.post(f"{V1}/companies/VALX/valuation", json={"discount_rate": 0.10})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["assets"] == [] and body["equity_value"] is None
    assert "No drug could be valued" in body["note"]
    assert body["discount_rate"] == 0.10
    assert "no terminal value" in body["method"].lower()


def test_valuation_rejects_an_impossible_discount_rate(client, ingested):
    assert client.post(f"{V1}/companies/VALX/valuation", json={"discount_rate": 5}).status_code == 422


def test_drugs_endpoint_lists_nothing_before_a_sync(client, ingested):
    body = client.get(f"{V1}/companies/VALX/drugs").get_json()
    assert body["drugs"] == [] and body["product_revenues"] == []


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


def test_signal_history_honours_limit(client, ingested):
    for _ in range(3):
        assert client.post(f"{V1}/companies/VALX/signals", json={
            "valuation_upside": 0.3, "manual_confidence": 0.8,
        }).status_code == 201
    capped = client.get(f"{V1}/companies/VALX/signals?limit=2").get_json()
    assert capped["count"] == 2
    assert len(capped["signal_runs"]) == 2
    assert client.get(f"{V1}/companies/VALX/signals?limit=0").status_code == 422
    assert client.get(f"{V1}/companies/VALX/signals?limit=abc").status_code == 422


def test_backtest_reports_no_fabricated_result_without_data(client, ingested):
    # A fresh signal (as_of today) with no future resolved catalysts -> null rate.
    client.post(f"{V1}/companies/VALX/signals", json={"valuation_upside": 0.3, "manual_confidence": 0.8})
    bt = client.get(f"{V1}/companies/VALX/signals/backtest").get_json()
    assert bt["directional_agreement_rate"] is None
    assert bt["evaluated"] == 0


def test_catalyst_ingest_endpoint(client, ingested):
    # TestConfig sets CATALYST_PROVIDER="mock", so this ingests deterministic samples.
    resp = client.post(f"{V1}/companies/VALX/catalysts/ingest")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["ingestion"]["provider"] == "mock"
    assert body["ingestion"]["added"] == 3
    assert body["ingestion"]["was_cached"] is False
    assert all(c["outcome"] == "pending" for c in body["catalysts"])
    assert any("SAMPLE" in w for w in body["ingestion"]["warnings"])

    # Idempotent: a second call adds nothing (served from cache) and never duplicates.
    again = client.post(f"{V1}/companies/VALX/catalysts/ingest").get_json()
    assert again["ingestion"]["added"] == 0
    assert again["ingestion"]["was_cached"] is True
    assert client.get(f"{V1}/companies/VALX/catalysts").get_json()["count"] == 3


def test_ingested_catalysts_expose_external_id(client, ingested):
    client.post(f"{V1}/companies/VALX/catalysts/ingest")
    listing = client.get(f"{V1}/companies/VALX/catalysts").get_json()
    assert all(c["external_id"] for c in listing["catalysts"])


def test_meta_reports_analyst_provider(client):
    assert client.get(f"{V1}/meta").get_json()["analyst_provider"] == "mock"


def test_analyst_ingest_and_read(client, ingested):
    # TestConfig sets ANALYST_PROVIDER="mock".
    resp = client.post(f"{V1}/companies/VALX/analysts/ingest")
    assert resp.status_code == 201
    ing = resp.get_json()["ingestion"]
    assert ing["provider"] == "mock"
    assert ing["analyst_count"] > 0
    assert ing["consensus_label"] is not None

    read = client.get(f"{V1}/companies/VALX/analysts").get_json()
    assert read["consensus"]["consensus_label"] == ing["consensus_label"]
    assert read["consensus"]["implied_upside"] is not None
    assert len(read["ratings"]) == 5
    assert all(r["institution"] for r in read["ratings"])


def test_analyst_coverage_reaches_the_score_once_and_only_once(client, ingested):
    """Analyst opinion used to fill the valuation component too, at 50 of 100 points."""
    client.post(f"{V1}/companies/VALX/analysts/ingest")
    body = client.post(f"{V1}/companies/VALX/signals", json={"manual_confidence": 0.8}).get_json()

    assert body["auto_derived"].get("analyst_consensus") == "analyst_coverage"
    assert "valuation_upside" not in body["auto_derived"]
    names = {c["name"] for c in body["components"]}
    assert "analyst_consensus" in names
    # The sample company has no valued drug, so valuation is absent with a stated reason.
    assert "valuation" not in names
    assert any(entry["name"] == "valuation" for entry in body["skipped"])


def test_financial_health_replaces_the_old_runway_only_component(client, ingested):
    body = client.post(f"{V1}/companies/VALX/signals", json={}).get_json()
    health = next(c for c in body["components"] if c["name"] == "financial_health")
    # VALX is cash-generative: no meaningful runway, so margin and dilution carry it.
    assert health["input_value"]["runway_quarters"] is None
    assert health["input_value"]["fcf_margin"] is not None
    assert body["auto_derived"].get("fcf_margin") == "sec_metrics"


def test_auto_derived_signal_values_the_company_once(client, ingested, monkeypatch):
    from app.services import rnpv_valuation

    calls = {"n": 0}
    original = rnpv_valuation.value_company

    def counting(session, company, **kwargs):
        calls["n"] += 1
        return original(session, company, **kwargs)

    monkeypatch.setattr("app.services.rnpv_valuation.value_company", counting)
    monkeypatch.setattr("app.api.v1.signals.value_company", counting)
    assert client.post(f"{V1}/companies/VALX/signals", json={"manual_confidence": 0.8}).status_code == 201
    assert calls["n"] == 1
