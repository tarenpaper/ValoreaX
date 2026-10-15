"""Tests for the AACT flat-file importer (stdlib only)."""
import json
from pathlib import Path

from importers import aact_flatfiles
from importers.contract import load_contract

FIXTURES = Path(__file__).parent / "fixtures"


def test_contract_loads_without_flask():
    contract = load_contract()
    assert contract.TARGET == "next_phase_transition"


def test_pipe_parser_reassembles_embedded_newlines():
    rows = list(aact_flatfiles.iter_pipe_rows(FIXTURES / "brief_summaries.txt"))
    assert len(rows) == 2
    first = rows[0]
    assert first["nct_id"] == "NCT00000001"
    assert "spans two physical lines" in first["description"]
    # Embedded newlines are preserved by the parser; text_features normalizes
    # whitespace downstream (" ".join(text.split())).
    assert "randomized study of examplemab" in first["description"].replace("\n", " ")


def test_build_study_maps_v2_shape():
    tables = aact_flatfiles.read_tables(FIXTURES)
    study = aact_flatfiles.build_study("NCT00000001", tables)
    protocol = study["protocolSection"]
    assert protocol["designModule"]["phases"] == ["PHASE2"]
    assert protocol["statusModule"]["overallStatus"] == "COMPLETED"
    assert protocol["designModule"]["studyType"] == "INTERVENTIONAL"
    assert protocol["designModule"]["enrollmentInfo"]["count"] == 120
    interventions = protocol["armsInterventionsModule"]["interventions"]
    assert {i["type"] for i in interventions} == {"DRUG"}
    assert protocol["sponsorCollaboratorsModule"]["leadSponsor"]["class"] == "INDUSTRY"
    primary = protocol["outcomesModule"]["primaryOutcomes"]
    assert len(primary) == 1 and primary[0]["measure"] == "Response rate"
    assert protocol["conditionsModule"]["conditions"] == ["Example Condition"]


def test_build_snapshots_emits_only_eligible(tmp_path):
    out = tmp_path / "snapshots.jsonl"
    manifest = aact_flatfiles.build_snapshots(
        FIXTURES, "2021-06-01T00:00:00Z", "aact-test", out)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    # Phase 3 and observational fixtures are excluded by the target-phase filter.
    assert [r["nct_id"] for r in rows] == ["NCT00000001"]
    assert manifest["snapshots_written"] == 1
    assert manifest["retrieved_at"] == "2021-06-01T00:00:00Z"
    # The contract's snapshot() already validated identity/hash/timestamps.
    contract = load_contract()
    for row in rows:
        contract.validate_snapshot(row)
    assert (tmp_path / "snapshots.jsonl.manifest.json").exists()


def test_phase_1_2_combo_is_excluded():
    assert aact_flatfiles._PHASE_MAP["phase 1/phase 2"] == ["PHASE1", "PHASE2"]
