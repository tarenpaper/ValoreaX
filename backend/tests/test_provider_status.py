from app.services.provider_status import provider_status


def test_readiness_does_not_expose_credentials_or_claim_live_health():
    config = {"SEC_PROVIDER": "sec_edgar", "SEC_USER_AGENT": "ValoreaX contact@example.com",
              "MARKET_DATA_PROVIDER": "twelve_data", "TWELVE_DATA_API_KEY": "",
              "CATALYST_PROVIDER": "clinicaltrials", "ANALYST_PROVIDER": "fmp",
              "FMP_API_KEY": "private-key", "NEWS_PROVIDER": "finnhub", "FINNHUB_API_KEY": "demo"}
    states = provider_status(config)
    assert states["SEC"]["state"] == "needs_setup"
    assert states["Prices"]["missing_setting"] == "TWELVE_DATA_API_KEY"
    assert states["Trials"]["state"] == "configured"
    assert states["Analysts"]["state"] == "configured"
    assert states["News"]["state"] == "needs_setup"
    assert "private-key" not in str(states)


def test_missing_live_credentials_return_useful_errors(app, client):
    assert client.post("/api/v1/companies", json={"ticker": "VALX"}).status_code == 201
    app.config.update(MARKET_DATA_PROVIDER="twelve_data", TWELVE_DATA_API_KEY="",
                      ANALYST_PROVIDER="fmp", FMP_API_KEY="", NEWS_PROVIDER="finnhub",
                      FINNHUB_API_KEY="")
    for endpoint, setting in [("prices/sync", "TWELVE_DATA_API_KEY"),
                              ("analysts/ingest", "FMP_API_KEY"), ("news/ingest", "FINNHUB_API_KEY")]:
        response = client.post(f"/api/v1/companies/VALX/{endpoint}")
        assert response.status_code == 502
        assert setting in response.get_json()["error"]["message"]


def test_sec_cache_namespaced_by_provider(db, client):
    from sqlalchemy import select

    from app.models import CacheEntry
    client.post("/api/v1/companies", json={"ticker": "VALX"})
    entry = db.session.execute(select(CacheEntry).where(CacheEntry.namespace == "company_facts")).scalar_one()
    assert entry.key.startswith("mock:")
