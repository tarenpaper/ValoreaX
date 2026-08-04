"""Model → JSON-safe dict serializers (output side).

Kept explicit (rather than auto-generated) so the API contract is obvious and
stable, and so provenance/quality fields are always present on financial values.
"""
from __future__ import annotations

import json
from datetime import date, datetime


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_or_none(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def company_to_dict(c, include_counts: bool = False) -> dict:
    data = {
        "id": c.id,
        "ticker": c.ticker,
        "cik": c.cik,
        "name": c.name,
        "sector": c.sector,
        "industry": c.industry,
        "exchange": c.exchange,
        "currency": c.currency,
        "description": c.description,
        "is_example": c.is_example,
        "source": c.source,
        "updated_at": _iso(c.updated_at),
    }
    if include_counts:
        data["counts"] = {
            "filings": len(c.filings),
            "metrics": len(c.metrics),
            "catalysts": len(c.catalysts),
            "signal_runs": len(c.signal_runs),
        }
    return data


def metric_to_dict(m) -> dict:
    return {
        "id": m.id,
        "concept": m.concept,
        "value": m.value,
        "unit": m.unit,
        "fiscal_year": m.fiscal_year,
        "fiscal_period": m.fiscal_period,
        "period_start": _iso(m.period_start),
        "period_end": _iso(m.period_end),
        "source": m.source,
        "provenance": {
            "xbrl_concept": m.xbrl_concept,
            "taxonomy": m.taxonomy,
            "accession_number": m.accession_number,
            "form": m.form,
        },
        "quality": {
            "status": m.status,
            "confidence": m.confidence,
            "note": m.quality_note,
        },
    }


def filing_to_dict(f) -> dict:
    return {
        "id": f.id,
        "accession_number": f.accession_number,
        "form": f.form,
        "fiscal_year": f.fiscal_year,
        "fiscal_period": f.fiscal_period,
        "period_end": _iso(f.period_end),
        "filed_date": _iso(f.filed_date),
        "source": f.source,
    }


def catalyst_to_dict(c) -> dict:
    return {
        "id": c.id,
        "company_id": c.company_id,
        "drug_program": c.drug_program,
        "indication": c.indication,
        "event_type": c.event_type,
        "trial_phase": c.trial_phase,
        "expected_date": _iso(c.expected_date),
        "actual_date": _iso(c.actual_date),
        "outcome": c.outcome,
        "source_url": c.source_url,
        "notes": c.notes,
        "source": c.source,
        "updated_at": _iso(c.updated_at),
    }


def signal_run_to_dict(s) -> dict:
    return {
        "id": s.id,
        "company_id": s.company_id,
        "signal": s.signal,
        "score": s.score,
        "confidence": s.confidence,
        "as_of_date": _iso(s.as_of_date),
        "engine_version": s.engine_version,
        "inputs_snapshot": _json_or_none(s.inputs_snapshot),
        "rationale": _json_or_none(s.rationale),
        "created_at": _iso(s.created_at),
    }


def price_to_dict(p) -> dict:
    return {"date": _iso(p.date), "close": p.close, "volume": p.volume, "source": p.source}
