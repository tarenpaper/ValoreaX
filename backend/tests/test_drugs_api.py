"""Drug sync, overrides and the sum-of-the-parts valuation over HTTP.

These run against the mock SEC provider, whose sample 10-K carries product revenue on
`srt:ProductOrServiceAxis` but no Gemini key, so they cover the honest degraded path: the
marketed drugs are modelled from XBRL and the pipeline is reported as unavailable rather
than invented.
"""
from __future__ import annotations

V1 = "/api/v1"


def synced(client, ticker="VALX"):
    assert client.post(f"{V1}/companies", json={"ticker": ticker}).status_code == 201
    resp = client.post(f"{V1}/companies/{ticker}/drugs/sync")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def test_sync_models_marketed_drugs_from_xbrl_product_lines(client):
    body = synced(client)
    assert body["accession_number"] and body["skipped"] is False
    assert body["product_lines"] == 3

    drugs = client.get(f"{V1}/companies/VALX/drugs").get_json()
    by_name = {d["name"]: d for d in drugs["drugs"]}
    assert set(by_name) == {"Trevaron", "Kelvido", "Collaboration and royalty revenue"}
    assert by_name["Trevaron"]["kind"] == "marketed"
    assert by_name["Trevaron"]["extracted"]["base_revenue"] == 800e6
    # A collaboration line is not a drug we can grow or lose exclusivity on.
    assert by_name["Collaboration and royalty revenue"]["kind"] == "royalty"
    assert {r["label"] for r in drugs["product_revenues"]} == set(by_name)


def test_sync_says_when_the_pipeline_could_not_be_read(client):
    """Without Gemini the pipeline is absent — and the response says so, rather than empty."""
    body = synced(client)
    assert any("Gemini is not configured" in w for w in body["warnings"])
    kinds = {d["kind"] for d in client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"]}
    assert "pipeline" not in kinds


def test_resync_is_skipped_until_a_new_filing_appears(client):
    synced(client)
    again = client.post(f"{V1}/companies/VALX/drugs/sync").get_json()
    assert again["skipped"] is True and again["drugs"] == 3
    forced = client.post(f"{V1}/companies/VALX/drugs/sync", json={"force": True}).get_json()
    assert forced["skipped"] is False


def test_resync_refreshes_the_filing_values_but_keeps_overrides(client):
    synced(client)
    drug = next(d for d in client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"]
                if d["name"] == "Trevaron")
    patched = client.patch(f"{V1}/drugs/{drug['id']}", json={"overrides": {"loe_year": 2039}})
    assert patched.status_code == 200 and patched.get_json()["overrides"] == {"loe_year": 2039}

    client.post(f"{V1}/companies/VALX/drugs/sync", json={"force": True})
    after = next(d for d in client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"]
                 if d["name"] == "Trevaron")
    assert after["overrides"] == {"loe_year": 2039}
    assert after["extracted"]["base_revenue"] == 800e6

    reset = client.patch(f"{V1}/drugs/{drug['id']}", json={"reset_overrides": True})
    assert reset.get_json()["overrides"] == {}


def test_overrides_are_validated_and_reach_the_valuation(client):
    synced(client)
    drug = next(d for d in client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"]
                if d["name"] == "Trevaron")
    assert client.patch(f"{V1}/drugs/{drug['id']}", json={"overrides": {"probability": 4}}).status_code == 422
    assert client.patch(f"{V1}/drugs/{drug['id']}", json={"overrides": {"loe_year": 12}}).status_code == 422

    before = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()
    client.patch(f"{V1}/drugs/{drug['id']}", json={"overrides": {"loe_year": 2028}})
    after = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()
    # A nearer patent cliff can only shorten the revenue stream.
    assert after["asset_value"] < before["asset_value"]
    entry = next(a for a in after["assets"] if a["name"] == "Trevaron")
    assert entry["provenance"]["sources"]["loe_year"] == "override"


def test_excluded_drugs_stay_visible_but_carry_no_value(client):
    synced(client)
    drug = next(d for d in client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"]
                if d["name"] == "Kelvido")
    client.patch(f"{V1}/drugs/{drug['id']}", json={"included": False})
    body = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()
    assert body["excluded"] == ["Kelvido"]
    assert "Kelvido" not in {a["name"] for a in body["assets"]}


def test_valuation_builds_a_waterfall_that_adds_up(client):
    synced(client)
    body = client.post(f"{V1}/companies/VALX/valuation",
                       json={"discount_rate": 0.11, "include_sensitivity": True}).get_json()
    assert body["discount_rate"] == 0.11
    assert sum(a["rnpv"] for a in body["assets"]) == body["asset_value"]
    assert round(body["equity_value"]) == round(
        body["asset_value"] - body["overhead_present_value"] + body["net_cash"])
    assert body["value_per_share"] == body["equity_value"] / body["shares_outstanding"]
    # Cost structure comes from the company's own filing, not a benchmark.
    assert body["economics"]["sources"]["gross_margin"] == "derived"
    assert body["economics"]["sources"]["tax_rate"] == "derived"
    grid = body["sensitivity"]
    assert len(grid["value_per_share"]) == len(grid["discount_rates"]) == 5
    assert all(len(row) == len(grid["revenue_multipliers"]) for row in grid["value_per_share"])
    # Value falls as the discount rate rises and rises with sales, in every row and column.
    middle = grid["value_per_share"][2]
    assert middle == sorted(middle)
    assert [row[2] for row in grid["value_per_share"]] == sorted(
        (row[2] for row in grid["value_per_share"]), reverse=True)


def test_valuation_reports_the_missing_filing_rather_than_a_number(client):
    """CARO has no sample 10-K, so there is nothing to value and the response says why."""
    assert client.post(f"{V1}/companies", json={"ticker": "CARO"}).status_code == 201
    sync = client.post(f"{V1}/companies/CARO/drugs/sync").get_json()
    assert sync["skipped"] is True and sync["drugs"] == 0
    assert any("no annual report" in w for w in sync["warnings"])

    body = client.post(f"{V1}/companies/CARO/valuation", json={}).get_json()
    assert body["equity_value"] is None and "No drug could be valued" in body["note"]


def test_another_account_cannot_reach_these_drugs(app, client, token_for):
    synced(client)
    drug_id = client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"][0]["id"]

    other = app.test_client()
    other.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token_for('22222222-2222-4222-8222-222222222222')}"
    assert other.get(f"{V1}/companies/VALX/drugs").status_code == 404
    assert other.post(f"{V1}/companies/VALX/drugs/sync").status_code == 404
    assert other.post(f"{V1}/companies/VALX/valuation", json={}).status_code == 404
    assert other.patch(f"{V1}/drugs/{drug_id}", json={"included": False}).status_code == 404


def test_override_can_supply_missing_pipeline_estimate(app, client):
    import json
    from app.extensions import db
    from app.models import Company, DrugAsset
    synced(client)
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker='VALX').one()
        row = DrugAsset(company_id=company.id, key='candidate', name='Candidate',
                        kind='pipeline', origin='filing_pipeline', extracted=json.dumps({
                            'peak_sales': None, 'probability': .524, 'launch_year': 2030,
                            'unvalued_reason': 'No disclosed patient population.'}))
        db.session.add(row)
        db.session.commit()
        asset_id = row.id
    response = client.patch(f'{V1}/drugs/{asset_id}', json={'overrides': {'peak_sales': 100e6}})
    assert response.status_code == 200
    value = client.post(f'{V1}/companies/VALX/valuation', json={}).get_json()
    assert any(a['name'] == 'Candidate' and a['rnpv'] is not None for a in value['assets'])
    client.patch(f'{V1}/drugs/{asset_id}', json={'reset_overrides': True})
    value = client.post(f'{V1}/companies/VALX/valuation', json={}).get_json()
    assert any(a['name'] == 'Candidate' for a in value['unvalued'])


def test_sync_retires_missing_assets_without_losing_user_edits(app, client):
    import json
    from app.extensions import db
    from app.models import Company, DrugAsset
    from app.services.drug_sync import _store_assets
    from app.services.rnpv_valuation import value_company
    synced(client)
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker='VALX').one()
        row = next(a for a in company.drug_assets if a.name == 'Trevaron')
        row.overrides = json.dumps({'base_revenue': 900e6})
        original = dict(key=row.key, name=row.name, kind=row.kind, origin=row.origin,
                        xbrl_member=row.xbrl_member, indication=row.indication,
                        phase=row.phase, extracted=json.loads(row.extracted))
        # An extraction failure must not retire records.
        _store_assets(db.session, company, [], retire_origins=())
        assert not json.loads(row.extracted).get('retired_from_filing')
        _store_assets(db.session, company, [], retire_origins={'sec_product_line'})
        db.session.flush()
        result = value_company(db.session, company)
        assert not result['assets']
        assert json.loads(row.overrides) == {'base_revenue': 900e6}
        # Reappearance restores eligibility and keeps overrides.
        _store_assets(db.session, company, [original], retire_origins={'sec_product_line'})
        db.session.flush()
        result = value_company(db.session, company)
        assert [a['name'] for a in result['assets']] == ['Trevaron']
        assert result['assets'][0]['provenance']['values']['base_revenue'] == 900e6
