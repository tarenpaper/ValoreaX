"""Exercise real JWT verification and account boundaries, without external services."""
import re
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.exceptions import PyJWKClientConnectionError

from app.models import Company, NewsArticle

OTHER = "22222222-2222-4222-8222-222222222222"
V1 = "/api/v1"


def test_every_research_route_requires_auth(app):
    anonymous = app.test_client()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/") or rule.endpoint == "health.health":
            continue
        path = re.sub(r"<[^>]+>", "1", rule.rule)
        for method in rule.methods - {"OPTIONS", "HEAD"}:
            response = anonymous.open(path, method=method)
            assert response.status_code == 401, (method, path, response.get_json())
            assert response.headers["Cache-Control"] == "private, no-store"
    assert anonymous.get(f"{V1}/health").status_code == 200


@pytest.mark.parametrize("claims", [
    {"exp": datetime.now(UTC) - timedelta(minutes=1)},
    {"iss": "https://attacker.example/auth/v1"},
    {"aud": "other-app"},
    {"sub": "not-a-user-id"},
    {"role": "service_role"},
    {"is_anonymous": True},
    {"iat": datetime.now(UTC) + timedelta(hours=1)},
])
def test_invalid_claims_rejected(app, token_for, claims):
    response = app.test_client().get(f"{V1}/auth/me", headers={
        "Authorization": f"Bearer {token_for(**claims)}",
    })
    assert response.status_code == 401


def test_tampered_unsigned_wrong_key_and_missing_exp_rejected(app, token_for, signing_key):
    claims = jwt.decode(token_for(), options={"verify_signature": False})
    other_key = ec.generate_private_key(ec.SECP256R1())
    missing_exp = {key: value for key, value in claims.items() if key != "exp"}
    tokens = ["garbage", jwt.encode(claims, key="", algorithm="none"),
              jwt.encode(claims, other_key, algorithm="ES256"),
              jwt.encode(missing_exp, signing_key, algorithm="ES256")]
    for token in tokens:
        assert app.test_client().get(f"{V1}/auth/me", headers={
            "Authorization": f"Bearer {token}",
        }).status_code == 401


def test_auth_configuration_and_provider_outage_fail_closed(app, client, monkeypatch):
    def unavailable(token):
        raise PyJWKClientConnectionError("unreachable")
    monkeypatch.setattr(app.extensions["token_verifier"].keys, "get_signing_key_from_jwt", unavailable)
    assert client.get(f"{V1}/companies").status_code == 503
    app.extensions["token_verifier"] = None
    assert client.get(f"{V1}/companies").status_code == 503


def test_account_profile_and_cors(client, app):
    response = client.get(f"{V1}/auth/me")
    assert response.get_json()["email"] == "researcher@example.com"
    assert "Authorization" in response.headers["Vary"]
    preflight = app.test_client().options(f"{V1}/companies", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    untrusted = client.get(f"{V1}/companies", headers={"Origin": "https://untrusted.example"})
    assert "Access-Control-Allow-Origin" not in untrusted.headers


def test_accounts_have_separate_company_trees(app, client, token_for):
    alice = client
    bob = app.test_client()
    bob.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token_for(OTHER)}"
    created = alice.post(f"{V1}/companies", json={"ticker": "VALX"})
    assert created.status_code == 201
    alice_id = created.get_json()["company"]["id"]
    assert bob.get(f"{V1}/companies").get_json()["companies"] == []
    assert bob.get(f"{V1}/watchlist").get_json()["count"] == 0
    for suffix in ["", "/summary", "/metrics", "/filings", "/catalysts", "/analysts",
                   "/news", "/signals", "/signals/backtest"]:
        assert bob.get(f"{V1}/companies/{alice_id}{suffix}").status_code == 404
    for suffix in ["/refresh", "/prices/sync", "/catalysts/ingest", "/analysts/ingest",
                   "/news/ingest", "/valuation", "/signals"]:
        assert bob.post(f"{V1}/companies/{alice_id}{suffix}", json={}).status_code == 404
    assert bob.get(f"{V1}/companies/VALX").status_code == 404
    catalyst = alice.post(f"{V1}/companies/VALX/catalysts", json={
        "drug_program": "Private program", "event_type": "pdufa", "outcome": "pending",
    }).get_json()
    for method in ["GET", "PATCH", "DELETE"]:
        assert bob.open(f"{V1}/catalysts/{catalyst['id']}", method=method,
                        json={"notes": "tamper"}).status_code == 404
    assert alice.get(f"{V1}/catalysts/{catalyst['id']}").status_code == 200
    own = bob.post(f"{V1}/companies", json={"ticker": "VALX"})
    assert own.status_code == 201
    assert own.get_json()["company"]["id"] != alice_id
    assert bob.get(f"{V1}/companies/VALX/catalysts").get_json()["count"] == 0
    assert alice.post(f"{V1}/companies/VALX/signals", json={"valuation_upside": .2}).status_code == 201
    assert bob.get(f"{V1}/companies/VALX/signals").get_json()["count"] == 0
    assert bob.post(f"{V1}/companies/VALX/refresh").status_code == 200
    assert alice.get(f"{V1}/catalysts/{catalyst['id']}").status_code == 200


def test_legacy_rows_and_other_accounts_excluded_from_aggregates(db, client):
    legacy = Company(ticker="OLD", name="Legacy", sector="Hidden sector")
    other = Company(ticker="OTHER", name="Other", sector="Other sector", owner_id=OTHER)
    db.session.add_all([legacy, other])
    db.session.flush()
    for company in [legacy, other]:
        db.session.add(NewsArticle(company_id=company.id, external_id="private", headline="Private",
                                   url="https://example.com", sentiment_score=1, provider="mock"))
    db.session.commit()
    assert client.get(f"{V1}/companies/OLD").status_code == 404
    assert client.get(f"{V1}/companies/{legacy.id}").status_code == 404
    assert client.get(f"{V1}/watchlist").get_json()["count"] == 0
    client.post(f"{V1}/companies", json={"ticker": "VALX"})
    assert client.get(f"{V1}/companies/VALX/news").get_json()["sector_sentiment"] == []
