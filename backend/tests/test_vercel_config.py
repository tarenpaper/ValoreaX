"""Serverless deployments require durable storage and pooled TLS connections."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import Config


def test_vercel_rejects_ephemeral_sqlite(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    cfg = Config()
    cfg.SQLALCHEMY_DATABASE_URI = "sqlite:///local.sqlite3"
    with pytest.raises(RuntimeError, match="persistent PostgreSQL"):
        cfg.as_flask_mapping()


@pytest.mark.parametrize("scheme", ["postgresql", "postgresql+psycopg2", "postgresql+psycopg"])
def test_vercel_uses_external_pooler_with_tls(monkeypatch, scheme):
    monkeypatch.setenv("VERCEL", "1")
    cfg = Config()
    cfg.SQLALCHEMY_DATABASE_URI = f"{scheme}://example:password@localhost/postgres"
    options = cfg.as_flask_mapping()["SQLALCHEMY_ENGINE_OPTIONS"]
    assert options["poolclass"] is NullPool
    assert options["connect_args"]["sslmode"] == "require"
    assert options["connect_args"]["connect_timeout"] == 10

    # Import the actual DBAPI without connecting: catches missing deployment drivers.
    engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI, **options)
    assert isinstance(engine.pool, NullPool)
    engine.dispose()


def test_local_postgres_keeps_existing_connection_defaults(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    cfg = Config()
    cfg.SQLALCHEMY_DATABASE_URI = "postgresql://example:password@localhost/postgres"
    assert "SQLALCHEMY_ENGINE_OPTIONS" not in cfg.as_flask_mapping()
