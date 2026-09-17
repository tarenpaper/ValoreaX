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
    from app.models import Company
    from app.services.drug_sync import _store_assets
    from app.services.rnpv_valuation import value_company
    synced(client)
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker='VALX').one()
        row = next(a for a in company.drug_assets if a.name == 'Trevaron')
        row.overrides = json.dumps({'base_revenue': 900e6})
        original = {"key": row.key, "name": row.name, "kind": row.kind,
                    "origin": row.origin, "xbrl_member": row.xbrl_member,
                    "indication": row.indication, "phase": row.phase,
                    "extracted": json.loads(row.extracted)}
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


def test_price_to_sotp_uses_latest_close_and_handles_unavailable_values(app, client):
    from datetime import date, timedelta

    from app.extensions import db
    from app.models import Company, MarketPrice
    synced(client)
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker='VALX').one()
        db.session.query(MarketPrice).filter_by(company_id=company.id).delete()
        db.session.commit()
    empty = client.post(f'{V1}/companies/VALX/valuation', json={}).get_json()
    assert empty['current_price'] is None and empty['price_to_sotp'] is None
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker='VALX').one()
        for days, price in [(-1, 25), (0, 50), (1, 1000)]:
            db.session.add(MarketPrice(company_id=company.id, date=date.today()+timedelta(days=days), close=price, source='mock'))
        db.session.commit()
    result = client.post(f'{V1}/companies/VALX/valuation', json={}).get_json()
    assert result['current_price'] == 50
    assert result['price_as_of'] == date.today().isoformat()
    assert result['price_to_sotp'] == 50 / result['value_per_share']
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker='VALX').one()
        for asset in company.drug_assets:
            asset.included = False
        db.session.commit()
    unvalued = client.post(f'{V1}/companies/VALX/valuation', json={}).get_json()
    assert unvalued['price_to_sotp'] is None


# --- Continuing value: the pipeline the filings cannot support ----------------------
def _pipeline_asset(app, key, name, code, phase="phase_3", probability=0.524):
    import json

    from app.extensions import db
    from app.models import Company, DrugAsset
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker="VALX").one()
        db.session.add(DrugAsset(
            company_id=company.id, key=key, name=name, kind="pipeline",
            origin="filing_pipeline", phase=phase, extracted=json.dumps({
                "peak_sales": None, "probability": probability, "launch_year": 2029,
                "unvalued_code": code, "unvalued_reason": f"stubbed {code}"})))
        db.session.commit()


def test_an_undisclosed_programme_gets_a_continuing_value_on_its_own_line(client, app):
    """Most large pharma discloses no populations, so the pipeline would read as worthless.

    Filed rather than Phase 3: VALX's median product is $565M, and half of that cannot
    cover a $300M-a-year Phase 3 run — which the discontinuation test below covers.
    """
    synced(client)
    _pipeline_asset(app, "vlx-1", "VLX-1", "no_population", phase="filed", probability=0.906)

    body = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()
    cv = body["continuing_value"]
    assert cv["value"] > 0 and [p["name"] for p in cv["programmes"]] == ["VLX-1"]
    assert cv["basis"] == "company_median_product"
    # Kept out of drug value, and the equity total includes it.
    assert all(a["name"] != "VLX-1" for a in body["assets"])
    assert round(body["equity_value"]) == round(
        body["asset_value"] + cv["value"] - body["overhead_present_value"] + body["net_cash"])


def test_cannibalisation_and_missing_success_rates_get_no_stand_in(client, app):
    """Those are real absences of value, not undisclosed ones."""
    synced(client)
    _pipeline_asset(app, "served", "Next-gen", "already_served")
    _pipeline_asset(app, "early", "Early", "no_success_rate", phase="preclinical",
                    probability=None)

    cv = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()["continuing_value"]
    assert cv["value"] == 0 and cv["programmes"] == []
    assert "No programme needed a stand-in" in cv["note"]


def test_a_programme_costing_more_than_it_returns_is_discontinued_not_subtracted(client, app):
    """A company would stop funding it, so its downside is bounded at zero."""
    synced(client)
    # Half of VALX's $565M median product cannot cover a $300M-a-year Phase 3 run.
    _pipeline_asset(app, "doomed", "Doomed", "no_population", phase="phase_3")

    cv = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()["continuing_value"]
    assert cv["value"] == 0 and cv["abandoned"] == 1
    assert "discontinued" in cv["note"]


def test_continuing_value_can_be_switched_off(client, app):
    synced(client)
    _pipeline_asset(app, "vlx-1", "VLX-1", "no_population", phase="filed", probability=0.906)
    on = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()
    off = client.post(f"{V1}/companies/VALX/valuation",
                      json={"include_continuing_value": False}).get_json()
    assert on["equity_value"] > off["equity_value"]
    assert off["continuing_value"]["value"] == 0


def test_a_retired_programme_gets_no_continuing_value(client, app):
    """Absent from the latest filing is not the same as undisclosed in it."""
    import json

    from app.extensions import db
    from app.models import Company
    synced(client)
    _pipeline_asset(app, "gone", "Gone", "no_population", phase="filed", probability=0.906)
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker="VALX").one()
        row = next(a for a in company.drug_assets if a.key == "gone")
        extracted = json.loads(row.extracted)
        extracted["retired_from_filing"] = True
        row.extracted = json.dumps(extracted)
        db.session.commit()

    cv = client.post(f"{V1}/companies/VALX/valuation", json={}).get_json()["continuing_value"]
    assert cv["value"] == 0 and cv["programmes"] == []


def test_sensitivity_matches_full_revaluation_with_and_without_continuing_value(client, app, monkeypatch):
    synced(client)
    _pipeline_asset(app, "vlx-1", "VLX-1", "no_population", phase="filed", probability=0.906)
    drugs = client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"]
    for enabled in (True, False):
        # Reset the revenue overrides before capturing the baseline grid.
        for drug in drugs:
            if drug["kind"] in ("marketed", "royalty"):
                assert client.patch(f"{V1}/drugs/{drug['id']}",
                                    json={"reset_overrides": True}).status_code == 200
        baseline = client.post(f"{V1}/companies/VALX/valuation",
                               json={"include_continuing_value": enabled}).get_json()
        grid = baseline["sensitivity"]
        assert grid["value_per_share"][2][2] == round(baseline["value_per_share"], 2)
        # Sensitivity varies drug sales while holding corporate overhead fixed.
        monkeypatch.setattr("app.services.rnpv_valuation.overhead_per_year",
                            lambda *args: baseline["overhead_per_year"])
        for row, col in ((0, 0), (4, 4)):
            multiplier = grid["revenue_multipliers"][col]
            for drug in drugs:
                if drug["kind"] in ("marketed", "royalty"):
                    response = client.patch(f"{V1}/drugs/{drug['id']}", json={"overrides": {
                        "base_revenue": drug["extracted"]["base_revenue"] * multiplier}})
                    assert response.status_code == 200
            direct = client.post(f"{V1}/companies/VALX/valuation", json={
                "include_continuing_value": enabled, "include_sensitivity": False,
                "discount_rate": grid["discount_rates"][row]}).get_json()
            assert grid["value_per_share"][row][col] == round(direct["value_per_share"], 2)


def test_duplicate_canonical_assets_can_be_persisted(client, app):
    from app.extensions import db
    from app.models import Company, DrugAsset
    from app.services.drug_assets import build_assets
    from app.services.drug_sync import _store_assets
    synced(client)
    assets = build_assets([], {"pipeline": [
        {"name": "Alpha Beta", "indication": "Condition", "phase": "filed"},
        {"name": "AB", "indication": "Condition", "phase": "filed"},
    ]}, 2026)
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker="VALX").one()
        # The storage boundary also tolerates repeated keys from other callers.
        _store_assets(db.session, company, assets + assets)
        db.session.commit()
        assert db.session.query(DrugAsset).filter_by(
            company_id=company.id, key="alphabeta|condition").count() == 1


def test_retired_old_assets_do_not_prevent_skipping_after_active_assets_rebuild(client, app):
    import json
    from app.extensions import db
    from app.models import Company, DrugAsset
    from app.services.drug_assets import ASSET_BUILD_VERSION
    synced(client)
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker="VALX").one()
        for asset in company.drug_assets:
            values = json.loads(asset.extracted)
            values["build_version"] = ASSET_BUILD_VERSION - 1
            asset.extracted = json.dumps(values)
        db.session.add(DrugAsset(company_id=company.id, key="old", name="Old product",
                                 kind="marketed", origin="sec_product_line", phase="approved",
                                 extracted=json.dumps({"build_version": ASSET_BUILD_VERSION - 1})))
        db.session.commit()
    rebuilt = client.post(f"{V1}/companies/VALX/drugs/sync").get_json()
    assert rebuilt["skipped"] is False
    drugs = client.get(f"{V1}/companies/VALX/drugs").get_json()["drugs"]
    old = next(d for d in drugs if d["key"] == "old")
    assert old["extracted"]["retired_from_filing"] is True
    again = client.post(f"{V1}/companies/VALX/drugs/sync").get_json()
    assert again["skipped"] is True
