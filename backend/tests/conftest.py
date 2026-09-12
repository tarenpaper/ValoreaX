"""Shared pytest fixtures."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db

ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"
AUTH_URL = "https://test-project.supabase.co"


@pytest.fixture(scope="session")
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture()
def token_for(signing_key):
    def issue(user_id=ACCOUNT_ID, **overrides):
        now = datetime.now(UTC)
        claims = {"sub": user_id, "email": "researcher@example.com", "role": "authenticated",
                  "iss": f"{AUTH_URL}/auth/v1", "aud": "authenticated",
                  "iat": now, "exp": now + timedelta(minutes=30)}
        claims.update(overrides)
        return jwt.encode(claims, signing_key, algorithm="ES256", headers={"kid": "test"})
    return issue


@pytest.fixture()
def app(signing_key, monkeypatch):
    config = TestConfig()
    config.SUPABASE_URL = AUTH_URL
    app = create_app(config)
    # Only replace network key discovery; real signature/claim verification still runs.
    monkeypatch.setattr(app.extensions["token_verifier"].keys, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key=signing_key.public_key()))
    yield app
    with app.app_context():
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app, token_for):
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token_for()}"
    return client


@pytest.fixture()
def db(app):
    with app.app_context():
        yield _db
