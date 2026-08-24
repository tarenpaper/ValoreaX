"""Unit tests for the ClinicalTrials.gov v2 mapping (pure, no network)."""
from __future__ import annotations

from datetime import date

from app.providers.clinicaltrials import (
    _map_study,
    _normalize_sponsor,
    _parse_partial_date,
    _phase_label,
)


def test_normalize_sponsor_strips_sec_artifacts_and_suffixes():
    assert _normalize_sponsor("VERTEX PHARMACEUTICALS INC / MA") == "VERTEX PHARMACEUTICALS"
    assert _normalize_sponsor("Pfizer Inc.") == "Pfizer"
    assert _normalize_sponsor("REGENERON PHARMACEUTICALS, INC.") == "REGENERON PHARMACEUTICALS"
    assert _normalize_sponsor("Moderna, Inc. / DE") == "Moderna"

# A representative CT.gov v2 study object (trimmed to the fields we consume).
STUDY = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT01234567",
            "briefTitle": "A Study of DRUGX in Solid Tumors",
            "organization": {"fullName": "Valorea Therapeutics"},
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "startDateStruct": {"date": "2024-03", "type": "ACTUAL"},
            "primaryCompletionDateStruct": {"date": "2026-09-30", "type": "ESTIMATED"},
            "completionDateStruct": {"date": "2027-03", "type": "ESTIMATED"},
        },
        "designModule": {"phases": ["PHASE2"], "studyType": "INTERVENTIONAL"},
        "conditionsModule": {"conditions": ["Metastatic Solid Tumors", "Breast Cancer"]},
        "armsInterventionsModule": {
            "interventions": [
                {"type": "DRUG", "name": "DRUGX"},
                {"type": "OTHER", "name": "Placebo"},
            ]
        },
    }
}


def test_parse_partial_date_precision():
    assert _parse_partial_date("2026-09-30") == (date(2026, 9, 30), "day")
    assert _parse_partial_date("2026-09") == (date(2026, 9, 1), "month")
    assert _parse_partial_date("2026") == (date(2026, 1, 1), "year")
    assert _parse_partial_date(None) == (None, None)
    assert _parse_partial_date("not-a-date") == (None, None)


def test_phase_label():
    assert _phase_label(["PHASE2"]) == "Phase 2"
    assert _phase_label(["PHASE1", "PHASE2"]) == "Phase 1 / Phase 2"
    assert _phase_label(["NA"]) is None
    assert _phase_label([]) is None


def test_map_study_full():
    record = _map_study(STUDY)
    assert record is not None
    assert record.drug_program == "DRUGX"                 # DRUG intervention wins over briefTitle
    assert record.event_type == "phase_readout"           # PHASE2 → readout
    assert record.indication == "Metastatic Solid Tumors"
    assert record.trial_phase == "Phase 2"
    assert record.expected_date == date(2026, 9, 30)      # primary completion preferred
    assert record.outcome == "pending"                    # outcomes are never inferred
    assert record.actual_date is None
    assert record.source == "clinicaltrials"
    assert record.source_url == "https://clinicaltrials.gov/study/NCT01234567"
    assert record.extra["nct_id"] == "NCT01234567"
    assert record.extra["date_field"] == "primaryCompletionDateStruct"
    assert record.extra["date_precision"] == "day"


def test_map_study_falls_back_to_completion_then_start():
    study = {"protocolSection": {
        "identificationModule": {"nctId": "NCT9", "briefTitle": "T"},
        "statusModule": {"startDateStruct": {"date": "2025-01-01"}},
        "designModule": {"phases": ["PHASE4"]},
    }}
    record = _map_study(study)
    assert record is not None
    assert record.event_type == "trial_completion"        # PHASE4 is not a readout phase
    assert record.expected_date == date(2025, 1, 1)
    assert record.extra["date_field"] == "startDateStruct"


def test_map_study_requires_nct_id():
    study = {"protocolSection": {
        "identificationModule": {"briefTitle": "No id"},
        "statusModule": {"primaryCompletionDateStruct": {"date": "2026-01-01"}},
    }}
    assert _map_study(study) is None


def test_map_study_requires_a_date():
    study = {"protocolSection": {
        "identificationModule": {"nctId": "NCT7", "briefTitle": "No date"},
        "designModule": {"phases": ["PHASE2"]},
    }}
    assert _map_study(study) is None
