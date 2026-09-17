"""Build a company's drug models from its latest 10-K, automatically.

One entry point, `sync_drugs`, does the whole chain: fetch the filing, parse product
revenue from XBRL, extract the pipeline and exclusivity dates with Plutus, assemble the
drugs, and persist. Filings never change, so everything keys off the accession number and
a company is only re-processed when it files a new 10-K.

Two rules protect the user's work and their bill:
* A re-sync refreshes `extracted` and never touches `overrides`.
* Extraction results are cached per accession, so the Gemini calls happen about once a
  year per company.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select

from app.models import DrugAsset, ProductRevenue
from app.providers.base import ProviderError
from app.services.drug_assets import ASSET_BUILD_VERSION, build_assets
from app.services.llm_filing import (
    _BUSINESS_SIGNALS,
    BUSINESS_BUDGET,
    EXCLUSIVITY_BUDGET,
    as_evidence,
    effective_loe,
    html_to_text,
    select_exclusivity_passages,
    select_passages,
)
from app.services.product_revenue import parse_product_revenue

EXTRACTION_TTL = 60 * 60 * 24 * 365  # a filing's text never changes


@dataclass
class SyncResult:
    accession_number: str | None
    product_lines: int
    assets: int
    unvalued: int
    skipped: bool = False
    warnings: list[str] | None = None


def _extract(cache, company, accession, report, config, warnings):
    """Pipeline, populations and exclusivity from the filing text, cached per accession."""
    if not report.primary_html or not config.get("GEMINI_API_KEY"):
        warnings.append("Gemini is not configured, so the pipeline and exclusivity dates are "
                        "unavailable. Marketed drugs are still modelled.")
        return {"pipeline": [], "marketed": [], "populations": []}, {"rows": [], "caveats": []}

    from app.providers.gemini import generate_filing_business, generate_filing_exclusivity

    text = html_to_text(report.primary_html)

    def cached(name, passages, label, generate):
        evidence = as_evidence(passages, label)
        if not evidence:
            return {}
        key = f"{company.id}:{accession}:{name}:v1"
        try:
            payload, _ = cache.get_or_set("filing_extraction", key, EXTRACTION_TTL,
                                          lambda: generate(config, evidence), provider="gemini")
            return payload
        except ProviderError as exc:
            warnings.append(f"{name.capitalize()} extraction failed: {exc}")
            return {}

    business = cached("business", select_passages(text, _BUSINESS_SIGNALS, BUSINESS_BUDGET),
                      "10-K business excerpt", generate_filing_business)
    exclusivity = cached("exclusivity", select_exclusivity_passages(text, EXCLUSIVITY_BUDGET),
                         "10-K exclusivity excerpt", generate_filing_exclusivity)
    return ({"pipeline": [], "marketed": [], "populations": [], **business,
             "extraction_complete": "pipeline" in business},
            {"rows": [], "caveats": [], **exclusivity})


def _apply_exclusivity(assets, exclusivity):
    """Attach each drug's US expiry year, taking the latest protection that applies."""
    from app.services.drug_assets import _alias_set

    by_product: dict[str, list[dict]] = {}
    for row in exclusivity.get("rows") or []:
        by_product.setdefault(row["product"], []).append(row)
    caveats = [c["text"] for c in (exclusivity.get("caveats") or [])]

    for asset in assets:
        names = _alias_set(asset["name"])
        match = next((rows for product, rows in by_product.items() if _alias_set(product) & names), None)
        if not match:
            continue
        territories = effective_loe(match)
        chosen = territories.get("us") or next(iter(territories.values()))
        asset["extracted"].update({
            "loe_year": chosen["expiry_year"], "loe_territory": chosen["territory"],
            "loe_protection": chosen["protection"], "loe_quote": chosen["quote"],
            "loe_caveats": caveats,
            "loe_by_territory": {t: r["expiry_year"] for t, r in territories.items()},
        })


def _store_product_lines(session, company, lines, accession):
    existing = {(row.member, row.fiscal_year): row for row in session.execute(
        select(ProductRevenue).where(ProductRevenue.company_id == company.id)).scalars()}
    seen = set()
    for line in lines:
        for year, values in line.years.items():
            seen.add((line.member, year))
            row = existing.get((line.member, year)) or ProductRevenue(
                company_id=company.id, member=line.member, fiscal_year=year)
            row.label, row.value, row.us_value = line.label, values.value, values.us_value
            row.classification, row.reason = line.classification, line.reason
            row.accession_number, row.revenue_tag = accession, values.revenue_tag
            row.geography_basis = values.geography_basis
            session.add(row)
    for key, row in existing.items():
        if key not in seen:
            session.delete(row)


def _store_assets(session, company, assets, retire_origins=()):
    """Upsert by key, refreshing what the filing says and preserving user overrides."""
    existing = {row.key: row for row in session.execute(
        select(DrugAsset).where(DrugAsset.company_id == company.id)).scalars()}
    seen = {asset["key"] for asset in assets}
    for key, row in existing.items():
        if key not in seen and row.origin in retire_origins:
            extracted = json.loads(row.extracted or "{}")
            extracted["retired_from_filing"] = True
            row.extracted = json.dumps(extracted)
    for asset in assets:
        row = existing.get(asset["key"]) or DrugAsset(company_id=company.id, key=asset["key"])
        existing[asset["key"]] = row
        row.name, row.kind, row.origin = asset["name"], asset["kind"], asset["origin"]
        row.xbrl_member, row.indication = asset["xbrl_member"], asset["indication"]
        row.phase = asset["phase"]
        row.extracted = json.dumps(asset["extracted"])
        session.add(row)


def sync_drugs(session, company, provider, cache, config, force: bool = False) -> SyncResult:
    """Refresh a company's drugs from its latest 10-K. Safe to call repeatedly."""
    warnings: list[str] = []
    try:
        accession = provider.latest_annual_report_id(company.ticker)
    except ProviderError as exc:
        return SyncResult(None, 0, 0, 0, skipped=True, warnings=[f"Could not reach SEC: {exc}"])
    if accession is None:
        return SyncResult(None, 0, 0, 0, skipped=True,
                          warnings=["This source has no annual report to model drugs from."])

    stored = session.execute(select(ProductRevenue.accession_number)
                             .where(ProductRevenue.company_id == company.id).limit(1)).scalar()
    # A filing never changes, so the accession alone normally decides. It cannot express a
    # change in what we extract from it, though, so stale-shaped assets rebuild as well.
    # The extraction itself stays cached, so this costs no Gemini call.
    extracted_assets = [json.loads(row.extracted or "{}") or {} for row in company.drug_assets]
    current_shape = all(
        values.get("build_version") == ASSET_BUILD_VERSION
        for values in extracted_assets if not values.get("retired_from_filing"))
    if stored == accession and current_shape and not force:
        count = len(company.drug_assets)
        return SyncResult(accession, len(company.product_revenues), count, 0, skipped=True)

    report = provider.get_annual_report(company.ticker)
    if report is None:
        return SyncResult(accession, 0, 0, 0, skipped=True,
                          warnings=["The filing's XBRL documents could not be read."])

    lines = parse_product_revenue(report.instance_xml, report.label_xml, report.definition_xml)
    business, exclusivity = _extract(cache, company, report.accession_number, report, config, warnings)

    year = int((report.period_end or "")[:4] or 0) or None
    assets = build_assets(lines, business, year or 0)
    _apply_exclusivity(assets, exclusivity)

    _store_product_lines(session, company, lines, report.accession_number)
    retire_origins = {"sec_product_line"} if lines else set()
    if business.get("extraction_complete"):
        retire_origins.add("filing_pipeline")
    _store_assets(session, company, assets, retire_origins)
    session.commit()

    unvalued = sum(1 for a in assets if a["extracted"].get("unvalued_reason"))
    return SyncResult(report.accession_number, len(lines), len(assets), unvalued, warnings=warnings)
