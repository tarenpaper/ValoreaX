"""Per-drug revenue lines and the drug models built from them.

`ProductRevenue` stores what a 10-K reports on `srt:ProductOrServiceAxis`, one row per
member and fiscal year, with the provenance needed to trust it: the accession, the XBRL
tag, and how geography or segment facts were combined.

`DrugAsset` is the modelled drug. Extracted values and user overrides live in separate
JSON columns so a newer 10-K can refresh what the filing says without discarding a user's
edits.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .common import TimestampMixin

# DrugAsset.kind
MARKETED = "marketed"
PIPELINE = "pipeline"
ROYALTY = "royalty"

# DrugAsset.origin
FROM_PRODUCT_LINE = "sec_product_line"   # an XBRL product revenue line
FROM_FILING_PIPELINE = "filing_pipeline"  # extracted from the 10-K's own pipeline text
MANUAL = "manual"


class ProductRevenue(TimestampMixin, db.Model):
    __tablename__ = "product_revenues"
    __table_args__ = (
        UniqueConstraint("company_id", "member", "fiscal_year", name="uq_product_revenue_member_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    member: Mapped[str] = mapped_column(String(128), index=True)   # XBRL QName
    label: Mapped[str] = mapped_column(String(256))
    fiscal_year: Mapped[int] = mapped_column(index=True)
    value: Mapped[float] = mapped_column(Float)                     # worldwide, USD
    us_value: Mapped[float | None] = mapped_column(Float)

    classification: Mapped[str] = mapped_column(String(24))         # product | royalty_collaboration | aggregate | other
    reason: Mapped[str | None] = mapped_column(Text)

    accession_number: Mapped[str | None] = mapped_column(String(32))
    revenue_tag: Mapped[str | None] = mapped_column(String(80))
    geography_basis: Mapped[str | None] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(32), default="sec_edgar")

    company = relationship("Company", back_populates="product_revenues")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProductRevenue {self.label} FY{self.fiscal_year} {self.classification}>"


class DrugAsset(TimestampMixin, db.Model):
    __tablename__ = "drug_assets"
    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_drug_asset_company_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    key: Mapped[str] = mapped_column(String(128), index=True)  # normalized name, for idempotent sync
    name: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(16), default=PIPELINE)
    origin: Mapped[str] = mapped_column(String(24), default=MANUAL)

    xbrl_member: Mapped[str | None] = mapped_column(String(128))
    indication: Mapped[str | None] = mapped_column(String(256))
    phase: Mapped[str | None] = mapped_column(String(24))
    modality: Mapped[str | None] = mapped_column(String(24))

    # Excluded drugs stay visible but contribute no value.
    included: Mapped[bool] = mapped_column(Boolean, default=True)

    # JSON text, kept apart so a re-sync refreshes `extracted` without touching `overrides`.
    extracted: Mapped[str | None] = mapped_column(Text)
    overrides: Mapped[str | None] = mapped_column(Text)

    company = relationship("Company", back_populates="drug_assets")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DrugAsset {self.name} {self.kind} included={self.included}>"
