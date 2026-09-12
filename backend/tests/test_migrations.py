"""Run migrations against disposable databases, including preservation of legacy rows."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.extensions import db

BACKEND = Path(__file__).resolve().parents[1]


def migrate(path, revision):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision], cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{path}", "AUTO_CREATE_SCHEMA": "false"},
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("legacy", [False, True])
def test_schema_upgrade_preserves_data_and_allows_personal_tickers(tmp_path, legacy):
    path = tmp_path / "migration.sqlite3"
    if legacy:
        migrate(path, "0001_initial")
        with sqlite3.connect(path) as connection:
            connection.execute("INSERT INTO companies (id, ticker, name, is_example, currency, source, created_at, updated_at) "
                               "VALUES (1, 'VALX', 'Legacy', 1, 'USD', 'mock', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO catalyst_events (company_id, drug_program, event_type, outcome, source, created_at, updated_at) "
                               "VALUES (1, 'Private note', 'pdufa', 'pending', 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
    migrate(path, "head")
    # A second run must be harmless.
    migrate(path, "head")
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), db.metadata) == []
    engine.dispose()
    with sqlite3.connect(path) as connection:
        if legacy:
            assert connection.execute("SELECT owner_id, name FROM companies WHERE id=1").fetchone() == (None, "Legacy")
            assert connection.execute("SELECT company_id, drug_program FROM catalyst_events").fetchone() == (1, "Private note")
        insert = ("INSERT INTO companies (ticker, owner_id, name, is_example, currency, source, created_at, updated_at) "
                  "VALUES ('VALX', ?, 'Personal', 0, 'USD', 'mock', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute(insert, ("11111111-1111-4111-8111-111111111111",))
        connection.execute(insert, ("22222222-2222-4222-8222-222222222222",))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, ("11111111-1111-4111-8111-111111111111",))
