"""Synthetic fixtures verify mechanics only; never evidence of clinical accuracy."""
import copy
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from conftest import ACCOUNT_ID

from app.ml.__main__ import main, read_jsonl
from app.ml.data import build_dataset, digest, snapshot, validate_label
from app.ml.features import expanded_features, features
from app.ml.prediction import predict, validate_artifact
from app.ml.training import temporal_split, train
from app.models import Company, RawProviderResponse
from app.providers.base import ProviderError
from app.providers.clinicaltrials import ClinicalTrialsCatalystProvider, StudyBatch
from app.services.llm_clinical import clinical_evidence_for


def study(n=1, allocation="RANDOMIZED"):
    return {"protocolSection": {
        "identificationModule": {"nctId": f"NCT{n:08d}", "briefTitle": "Synthetic trial"},
        "statusModule": {"overallStatus": "RECRUITING"},
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE2"],
                         "enrollmentInfo": {"count": 100, "type": "ESTIMATED"},
                         "designInfo": {"allocation": allocation}},
        "armsInterventionsModule": {"interventions": [{"name": "Synthetic drug", "type": "DRUG"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "Synthetic primary endpoint"}]},
    }}


def label(n=1, year=2020, outcome=1):
    return {"nct_id": f"NCT{n:08d}", "target": "primary_endpoint_success", "outcome": outcome,
            "drug_group": f"synthetic-family-{n}", "prediction_at": f"{year}-02-01T00:00:00Z",
            "outcome_at": f"{year}-06-01T00:00:00Z", "known_at": f"{year}-07-01T00:00:00Z",
            "reviewed_at": "2024-01-01T00:00:00Z", "reviewer": "Synthetic test curator",
            "source_url": "https://example.com/synthetic-fixture", "rationale": "Synthetic test only"}


def test_features_exclude_outcomes_actual_enrollment_and_identity():
    original = study()
    changed = copy.deepcopy(original)
    changed["resultsSection"] = {"outcomeMeasuresModule": {"pValue": 0.01}}
    changed["hasResults"] = True
    p = changed["protocolSection"]
    p["statusModule"] = {"overallStatus": "TERMINATED", "whyStopped": "efficacy"}
    p["identificationModule"]["nctId"] = "NCT99999999"
    assert features(original) == features(changed)
    p["designModule"]["enrollmentInfo"] = {"count": 999, "type": "ACTUAL"}
    assert features(changed)["planned_enrollment_log"] == 0
    assert features(changed)["planned_enrollment_missing"] == 1


def test_snapshot_integrity_and_temporal_join():
    old = snapshot(study(), "2020-01-01T00:00:00Z")
    future = snapshot(study(), "2020-03-01T00:00:00Z")
    rows, counts = build_dataset([future, old], [label()], "2025-01-01T00:00:00Z")
    assert not counts
    assert rows[0]["snapshot"] == old
    rows, counts = build_dataset([future], [label()], "2025-01-01T00:00:00Z")
    assert rows == [] and counts == {"no_snapshot_before_prediction": 1}
    old["study"]["hasResults"] = True
    with pytest.raises(ValueError, match="hash"):
        build_dataset([old], [label()], "2025-01-01T00:00:00Z")


@pytest.mark.parametrize("change", [{"target": "approval"}, {"outcome": True}, {"outcome": "completed"},
                                   {"reviewer": ""}, {"known_at": "2019-01-01T00:00:00Z"},
                                   {"prediction_at": "2020-01-01"}, {"source_url": "javascript:bad"}])
def test_invalid_labels_rejected(change):
    with pytest.raises(ValueError):
        validate_label(label() | change)


def test_unknown_unavailable_duplicate_and_resolved_outcomes():
    s = snapshot(study(), "2020-01-01T00:00:00Z")
    assert build_dataset([s], [], "2025-01-01T00:00:00Z") == ([], {})
    assert build_dataset([s], [label()], "2023-01-01T00:00:00Z")[1] == {"label_not_available_as_of": 1}
    with pytest.raises(ValueError, match="Duplicate"):
        build_dataset([s], [label(), label()], "2025-01-01T00:00:00Z")
    terminal = study()
    terminal["protocolSection"]["statusModule"]["overallStatus"] = "COMPLETED"
    assert build_dataset([snapshot(terminal, s["retrieved_at"])], [label()],
                         "2025-01-01T00:00:00Z")[1] == {"ineligible_snapshot": 1}


def test_temporal_split_purges_drug_groups_and_late_outcomes():
    rows = [{"label": label(1, 2020)}, {"label": label(2, 2021) | {"drug_group": "synthetic-family-1"}},
            {"label": label(3, 2021)}, {"label": label(4, 2022)},
            {"label": label(5, 2020) | {"known_at": "2021-01-01T00:00:00Z"}}]
    split, excluded = temporal_split(rows, "2020-12-31T23:59:59Z", "2021-12-31T23:59:59Z")
    assert [len(s) for s in split.values()] == [1, 1, 1]
    assert excluded == {"outcome_unavailable_at_fit_boundary": 1, "drug_group_overlap": 1}


@pytest.fixture(scope="module")
def trained():
    pytest.importorskip("sklearn")
    snapshots, labels = [], []
    for year, count in ((2020, 120), (2021, 50), (2022, 50)):
        for i in range(count):
            n = len(labels) + 1
            allocation = "RANDOMIZED" if i % 2 else "NON_RANDOMIZED"
            snapshots.append(snapshot(study(n, allocation), f"{year}-01-01T00:00:00Z"))
            labels.append(label(n, year, int(i % 2 == 1)))
    return train(snapshots, labels, train_until="2020-12-31T23:59:59Z",
                 calibrate_until="2021-12-31T23:59:59Z", as_of="2025-01-01T00:00:00Z")


def test_training_metrics_and_json_inference_agree(trained):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    validate_artifact(trained)
    assert trained["status"] == "research_candidate"
    assert trained["evaluation"]["model"]["brier"] < trained["evaluation"]["phase_baseline"]["brier"]
    fresh = snapshot(study(999), "2025-06-01T00:00:00Z")
    output = predict(fresh, json.loads(json.dumps(trained)))
    f = expanded_features(fresh["study"])
    vector = np.array([[f.get(name, 0) / scale for name, scale in zip(
        trained["feature_names"], trained["scale"], strict=True)]])
    raw = (vector @ np.array(trained["coefficients"]) + trained["intercept"]).item()
    calibrator = LogisticRegression()
    calibrator.classes_ = np.array([0, 1])
    calibrator.coef_ = np.array([[trained["calibration_slope"]]])
    calibrator.intercept_ = np.array([trained["calibration_intercept"]])
    calibrator.n_features_in_ = 1
    assert output["probability"] == pytest.approx(calibrator.predict_proba([[raw]])[0, 1])
    assert output["drivers"]


def test_prediction_abstains_when_not_supported(trained):
    assert predict(snapshot(study(999), "2025-06-01T00:00:00Z"), None)["probability"] is None
    assert predict(snapshot(study(1), "2025-06-01T00:00:00Z"), trained)["probability"] is None
    assert predict(snapshot(study(999), "2024-06-01T00:00:00Z"), trained)["probability"] is None
    unseen = study(999, "NEW_ALLOCATION")
    assert predict(snapshot(unseen, "2025-06-01T00:00:00Z"), trained)["probability"] is None
    completed = study(999)
    completed["hasResults"] = True
    assert predict(snapshot(completed, "2025-06-01T00:00:00Z"), trained)["probability"] is None
    failed = copy.deepcopy(trained)
    failed["status"] = "evaluation_failed"
    failed["model_id"] = digest({k: v for k, v in failed.items() if k != "model_id"})
    assert predict(snapshot(study(999), "2025-06-01T00:00:00Z"), failed)["probability"] is None
    failed["intercept"] = 999
    with pytest.raises(ValueError, match="integrity"):
        validate_artifact(failed)


def test_training_rejects_small_dataset():
    pytest.importorskip("sklearn")
    with pytest.raises(ValueError, match="Insufficient train data"):
        train([], [], train_until="2020-12-31T23:59:59Z", calibrate_until="2021-12-31T23:59:59Z",
              as_of="2025-01-01T00:00:00Z")


def response(payload):
    r = Mock()
    r.json.return_value = payload
    return r


def test_full_ingestion_paginates_deduplicates_and_discloses_truncation():
    provider = ClinicalTrialsCatalystProvider("test")
    provider._session = Mock()
    provider._session.get.side_effect = [response({"studies": [study(1)], "nextPageToken": "page2"}),
                                         response({"studies": [study(1), study(2)], "nextPageToken": "page3"})]
    batch = provider.fetch_studies(query="AREA[StudyType]INTERVENTIONAL", limit=2)
    assert len(batch.studies) == 2 and batch.truncated
    assert provider._session.get.call_count == 2
    # No milestone date is required for ML ingestion.
    assert not batch.studies[0]["protocolSection"]["statusModule"].get("startDateStruct")


def test_pagination_rejects_repeated_token_and_malformed_page():
    provider = ClinicalTrialsCatalystProvider("test")
    provider._session = Mock()
    provider._session.get.return_value = response({"studies": [study()], "nextPageToken": "same"})
    with pytest.raises(ProviderError, match="pagination"):
        provider.fetch_studies(query="drug")
    provider._session.get.return_value = response({"studies": [None]})
    with pytest.raises(ProviderError, match="malformed"):
        provider.fetch_studies(query="drug")


def test_cli_ingest_is_idempotent_and_preserves_first_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(ClinicalTrialsCatalystProvider, "fetch_studies",
                        lambda *a, **k: StudyBatch([study()], False))
    path = str(tmp_path / "snapshots.jsonl")
    main(["ingest", "--query", "test", "--output", path])
    first = read_jsonl(path)
    main(["ingest", "--query", "test", "--output", path])
    assert read_jsonl(path) == first
    assert datetime.fromisoformat(first[0]["retrieved_at"]).date() == datetime.now(UTC).date()
    assert json.loads((tmp_path / "snapshots.jsonl.manifest.json").read_text())["added"] == 0


def test_clinical_ml_api_is_account_scoped_and_no_model_is_explicit(client, db, app, monkeypatch):
    c = Company(ticker="TEST", name="Test sponsor", owner_id=ACCOUNT_ID)
    other = Company(ticker="SECRET", name="Other", owner_id="other-user")
    db.session.add_all([c, other])
    db.session.commit()
    app.config["CLINICAL_ML_MODEL_PATH"] = ""
    assert client.get("/api/v1/companies/SECRET/clinical-ml").status_code == 404
    assert client.post(f"/api/v1/companies/{other.id}/clinical-ml/ingest").status_code == 404
    result = client.get("/api/v1/companies/TEST/clinical-ml").get_json()
    assert result["model_status"] == "not_configured" and result["trials"] == []
    assert client.post("/api/v1/companies/TEST/clinical-ml/ingest").status_code == 422
    app.config["CATALYST_PROVIDER"] = "clinicaltrials"
    monkeypatch.setattr(ClinicalTrialsCatalystProvider, "fetch_studies",
                        lambda *a, **k: StudyBatch([study()], True))
    response = client.post("/api/v1/companies/TEST/clinical-ml/ingest")
    assert response.status_code == 201
    data = response.get_json()
    assert data["truncated"] and data["trials"][0]["probability"] is None
    evidence = clinical_evidence_for(db.session, c)
    assert evidence[0]["data"]["cohort_truncated"] is True
    assert evidence[1]["data"]["study"]["protocolSection"]["outcomesModule"]
    assert "model_id" not in json.dumps(evidence)
    assert clinical_evidence_for(db.session, other)[0]["data"]["total_trials"] == 0
    assert db.session.query(RawProviderResponse).filter_by(resource_type="clinical_ml_cohort").count() == 1
    # Empty refresh clears latest coverage without deleting history.
    monkeypatch.setattr(ClinicalTrialsCatalystProvider, "fetch_studies",
                        lambda *a, **k: StudyBatch([], False))
    assert client.post("/api/v1/companies/TEST/clinical-ml/ingest").get_json()["trials"] == []
    assert clinical_evidence_for(db.session, c)[0]["data"]["total_trials"] == 0
    app.config["CLINICAL_ML_MODEL_PATH"] = "/missing/model.json"
    assert client.get("/api/v1/companies/TEST/clinical-ml").get_json()["model_error"]
