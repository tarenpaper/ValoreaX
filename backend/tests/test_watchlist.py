"""Tests for the watchlist aggregation endpoint (mock providers, offline)."""
from __future__ import annotations

V1 = "/api/v1"


def test_watchlist_empty(client):
    body = client.get(f"{V1}/watchlist").get_json()
    assert body["count"] == 0
    assert body["companies"] == []


def test_watchlist_aggregates_price_and_status(client):
    assert client.post(f"{V1}/companies", json={"ticker": "VALX"}).status_code == 201
    client.post(f"{V1}/companies/VALX/prices/sync")        # mock market prices
    client.post(f"{V1}/companies/VALX/catalysts/ingest")   # mock catalysts (TestConfig)

    body = client.get(f"{V1}/watchlist").get_json()
    assert body["count"] == 1
    row = body["companies"][0]
    assert row["ticker"] == "VALX"
    assert row["price"] is not None
    assert len(row["series"]) > 1                          # sparkline points
    assert row["clinical_status"]["state"] in {"upcoming", "overdue", "recent", "none"}
    assert row["clinical_status"]["label"]


def test_watchlist_reflects_latest_signal(client):
    client.post(f"{V1}/companies", json={"ticker": "VALX"})
    client.post(f"{V1}/companies/VALX/signals", json={"valuation_upside": 0.3, "manual_confidence": 0.8})
    row = client.get(f"{V1}/watchlist").get_json()["companies"][0]
    assert row["signal"] in {"long", "short", "watchlist"}


def test_watchlist_aggregates_two_companies_in_one_payload(client):
    assert client.post(f"{V1}/companies", json={"ticker": "VALX"}).status_code == 201
    assert client.post(f"{V1}/companies", json={"ticker": "CARO"}).status_code == 201
    client.post(f"{V1}/companies/VALX/prices/sync")
    client.post(f"{V1}/companies/CARO/prices/sync")
    body = client.get(f"{V1}/watchlist").get_json()
    assert {row["ticker"] for row in body["companies"]} == {"CARO", "VALX"}
    assert all(row["price"] is not None for row in body["companies"])
