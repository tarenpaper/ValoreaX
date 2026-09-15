"""Per-drug revenue lines and drug models for the sum-of-the-parts rNPV valuation."""
import sqlalchemy as sa
from alembic import op

revision = "0004_drug_assets"
down_revision = "0003_backend_only_access"
branch_labels = None
depends_on = None

NEW_TABLES = ("product_revenues", "drug_assets")


def upgrade():
    op.create_table(
        "product_revenues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("member", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("us_value", sa.Float(), nullable=True),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("accession_number", sa.String(length=32), nullable=True),
        sa.Column("revenue_tag", sa.String(length=80), nullable=True),
        sa.Column("geography_basis", sa.String(length=48), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="sec_edgar"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "member", "fiscal_year", name="uq_product_revenue_member_year"),
    )
    op.create_index(op.f("ix_product_revenues_company_id"), "product_revenues", ["company_id"])
    op.create_index(op.f("ix_product_revenues_member"), "product_revenues", ["member"])
    op.create_index(op.f("ix_product_revenues_fiscal_year"), "product_revenues", ["fiscal_year"])

    op.create_table(
        "drug_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="pipeline"),
        sa.Column("origin", sa.String(length=24), nullable=False, server_default="manual"),
        sa.Column("xbrl_member", sa.String(length=128), nullable=True),
        sa.Column("indication", sa.String(length=256), nullable=True),
        sa.Column("phase", sa.String(length=24), nullable=True),
        sa.Column("modality", sa.String(length=24), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extracted", sa.Text(), nullable=True),
        sa.Column("overrides", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "key", name="uq_drug_asset_company_key"),
    )
    op.create_index(op.f("ix_drug_assets_company_id"), "drug_assets", ["company_id"])
    op.create_index(op.f("ix_drug_assets_key"), "drug_assets", ["key"])

    # Match 0003: these tables live in Supabase's exposed public schema, so they must not
    # be readable without going through the backend.
    if op.get_bind().dialect.name == "postgresql":
        for table in NEW_TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    op.drop_table("drug_assets")
    op.drop_table("product_revenues")
