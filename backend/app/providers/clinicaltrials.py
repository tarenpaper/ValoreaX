"""Live ClinicalTrials.gov v2 adapter — free, no API key required.

Queries the public REST API (https://clinicaltrials.gov/api/v2/studies) by
sponsor name and maps each study to a `CatalystRecord`. A descriptive
User-Agent with contact info is sent, matching how we treat SEC EDGAR.

Honesty boundaries (mirrored by the mock):
  * We ingest trial **milestone dates** (primary completion / completion /
    start) as *pending* catalysts. We never infer a clinical **outcome** —
    outcomes stay ``pending`` until a human records them.
  * Sponsor matching is by name and therefore approximate; the raw payload is
    retained upstream (RawProviderResponse) so any match can be audited.

The pure `_map_study` / `_parse_partial_date` helpers hold all the mapping logic
so they can be unit-tested against a captured fixture with no network access.
"""
from __future__ import annotations

import re
from datetime import date

import requests

from .base import CatalystProvider, CatalystRecord, ProviderError

# Corporate suffixes / SEC artifacts to drop so an issuer name matches CT.gov's
# sponsor strings (e.g. "VERTEX PHARMACEUTICALS INC / MA" → "VERTEX PHARMACEUTICALS").
_CORP_SUFFIX = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|plc|llc|lp|"
    r"holdings|group|sa|ag|nv|the)\b\.?",
    re.IGNORECASE,
)


def _normalize_sponsor(name: str) -> str:
    """Strip the SEC '/ STATE' suffix and common corporate suffixes from an issuer name."""
    name = re.split(r"\s*/\s*[A-Za-z]{2}\s*$", name)[0]  # drop trailing "/ MA"
    name = _CORP_SUFFIX.sub(" ", name)
    name = re.sub(r"[.,]", " ", name)
    return " ".join(name.split()).strip()


# Phases that generate topline data — their primary-completion date is a readout.
_READOUT_PHASES = {"PHASE1", "PHASE1/PHASE2", "PHASE2", "PHASE2/PHASE3", "PHASE3"}
_PHASE_LABELS = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE1/PHASE2": "Phase 1/2",
    "PHASE2": "Phase 2",
    "PHASE2/PHASE3": "Phase 2/3",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": None,
}


def _parse_partial_date(value: str | None) -> tuple[date | None, str | None]:
    """Parse a CT.gov date that may be YYYY, YYYY-MM, or YYYY-MM-DD.

    Missing components are padded to the start of the period; the returned
    precision ('day'/'month'/'year') is kept for provenance.
    """
    if not value:
        return None, None
    parts = str(value).split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        parsed = date(year, month, day)
    except (ValueError, IndexError):
        return None, None
    precision = {1: "year", 2: "month"}.get(len(parts), "day")
    return parsed, precision


def _phase_label(phases: list[str]) -> str | None:
    labels = [_PHASE_LABELS.get(p, p.title()) for p in phases if _PHASE_LABELS.get(p, p) is not None]
    return " / ".join(labels) if labels else None


def _map_study(study: dict) -> CatalystRecord | None:
    """Map one CT.gov v2 study object to a CatalystRecord (or None if unusable)."""
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    conditions = protocol.get("conditionsModule", {})
    arms = protocol.get("armsInterventionsModule", {})

    nct_id = ident.get("nctId")
    if not nct_id:
        return None

    # Expected date: primary completion is the best readout proxy; fall back.
    expected_date = None
    precision = None
    date_field = None
    for field_name in ("primaryCompletionDateStruct", "completionDateStruct", "startDateStruct"):
        parsed, precision = _parse_partial_date((status.get(field_name) or {}).get("date"))
        if parsed is not None:
            expected_date = parsed
            date_field = field_name
            break
    if expected_date is None:
        return None  # nothing dateable → not an actionable catalyst

    phases = design.get("phases", []) or []
    is_readout = any(p in _READOUT_PHASES for p in phases)
    event_type = "phase_readout" if is_readout else "trial_completion"

    interventions = arms.get("interventions", []) or []
    drug = next(
        (i.get("name") for i in interventions if i.get("type") in {"DRUG", "BIOLOGICAL"} and i.get("name")),
        None,
    )
    drug_program = drug or ident.get("briefTitle") or nct_id
    condition_list = conditions.get("conditions", []) or []

    overall_status = status.get("overallStatus")
    return CatalystRecord(
        drug_program=drug_program[:256],
        event_type=event_type,
        indication=(condition_list[0] if condition_list else None),
        trial_phase=_phase_label(phases),
        expected_date=expected_date,
        actual_date=None,          # never inferred — outcomes are recorded by humans
        outcome="pending",
        source_url=f"https://clinicaltrials.gov/study/{nct_id}",
        notes=(
            f"Trial milestone ({date_field}) from ClinicalTrials.gov — a scheduled "
            f"date, not a resolved outcome. Status: {overall_status or 'unknown'}."
        ),
        source="clinicaltrials",
        extra={
            "nct_id": nct_id,
            "overall_status": overall_status,
            "phases": phases,
            "date_field": date_field,
            "date_precision": precision,
            "study_evidence": {
                "protocolSection": protocol,
                "resultsSection": study.get("resultsSection"),
                "hasResults": study.get("hasResults", False),
            },
        },
    )


class ClinicalTrialsCatalystProvider(CatalystProvider):
    """Adapter over the public ClinicalTrials.gov v2 REST API."""

    name = "clinicaltrials"

    def __init__(
        self,
        user_agent: str,
        base_url: str = "https://clinicaltrials.gov/api/v2",
        timeout: int = 20,
        max_studies: int = 25,
    ) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_studies = max_studies

    def fetch(self, ticker: str, company_name: str | None = None) -> list[CatalystRecord]:
        sponsor = _normalize_sponsor(company_name or "") or (ticker or "").strip()
        if not sponsor:
            return []
        payload = self._get_studies(sponsor)
        records: list[CatalystRecord] = []
        for study in payload.get("studies", []) or []:
            record = _map_study(study)
            if record is not None:
                records.append(record)
        return records

    def _get_studies(self, sponsor: str) -> dict:
        url = f"{self._base_url}/studies"
        params = {
            "query.spons": sponsor,
            "pageSize": self._max_studies,
            "format": "json",
            # Newest/most-relevant first so the capped page favors active trials.
            "sort": "LastUpdatePostDate:desc",
        }
        try:
            resp = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"ClinicalTrials.gov request failed: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(
                f"ClinicalTrials.gov returned HTTP {resp.status_code} for sponsor {sponsor!r}."
            )
        try:
            return resp.json()
        except ValueError as exc:  # pragma: no cover
            raise ProviderError("ClinicalTrials.gov returned non-JSON.") from exc
