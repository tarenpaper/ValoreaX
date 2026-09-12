"""Keep research tables private when hosted in Supabase's exposed public schema."""
from alembic import op

revision = "0003_backend_only_access"
down_revision = "0002_account_workspaces"
branch_labels = None
depends_on = None

TABLES = (
    "alembic_version", "benchmark_prices", "cache_entries", "companies",
    "raw_provider_responses", "analyst_consensus", "analyst_ratings",
    "catalyst_events", "filings", "market_prices", "news_articles",
    "signal_runs", "financial_metrics",
)


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    # No browser policies: Flask authenticates requests and scopes each account.
    # The database owner used by the backend retains access through PostgreSQL.
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    raise RuntimeError("Disabling account-data protection is intentionally unsupported.")
