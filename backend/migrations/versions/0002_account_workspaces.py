"""Isolate each account's company tree; preserve legacy data as unassigned."""
import sqlalchemy as sa
from alembic import op

revision = "0002_account_workspaces"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(36), nullable=True))
        batch.drop_index("ix_companies_ticker")
        batch.create_index("ix_companies_ticker", ["ticker"], unique=False)
        batch.create_index("ix_companies_owner_id", ["owner_id"], unique=False)
        batch.create_unique_constraint("uq_companies_owner_ticker", ["owner_id", "ticker"])


def downgrade():
    raise RuntimeError("Removing account isolation would mix private workspaces; downgrade disabled.")
