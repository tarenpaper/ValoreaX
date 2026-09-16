"""Explicit watchlist membership and named acronym baskets."""
import sqlalchemy as sa
from alembic import op

revision = "0005_watchlist_baskets"
down_revision = "0004_drug_assets"
branch_labels = None
depends_on = None

NEW_TABLES = ("watchlist_baskets",)


def upgrade():
    # Existing companies stay watched. An account already holding more than the cap keeps
    # everything it has and is simply blocked from adding more until it removes some;
    # silently truncating someone's list on deploy would be worse than being over.
    op.add_column("companies",
                  sa.Column("watched", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "watchlist_baskets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        # Ordered member tickers as JSON: a basket holds at most seven, order matters for
        # display, and nothing needs to query which baskets contain a given ticker.
        sa.Column("tickers", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_basket_owner_name"),
    )
    op.create_index(op.f("ix_watchlist_baskets_owner_id"), "watchlist_baskets", ["owner_id"])

    # Match 0003/0004: this table lives in Supabase's exposed public schema, so it must not
    # be readable without going through the backend.
    if op.get_bind().dialect.name == "postgresql":
        for table in NEW_TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    op.drop_table("watchlist_baskets")
    op.drop_column("companies", "watched")
