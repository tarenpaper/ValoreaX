"""Dependency-light inference using exactly the offline feature contract."""
import json
import math
from pathlib import Path

from .data import TARGET, TRANSITIONS, digest, eligibility, timestamp, validate_snapshot
from .features import FEATURE_VERSION, expanded_features, phase
from .text_features import protocol_text, tfidf_values


def validate_artifact(artifact: dict) -> dict:
    if (artifact.get("artifact_version") != 2 or artifact.get("target") != TARGET
            or artifact.get("feature_version") != FEATURE_VERSION):
        raise ValueError("Unsupported clinical model artifact.")
    if artifact.get("model_id") != digest({k: v for k, v in artifact.items() if k != "model_id"}):
        raise ValueError("Clinical model integrity check failed.")
    names = artifact["feature_names"]
    if not names or len(names) != len(set(names)):
        raise ValueError("Invalid model feature names.")
    if not len(names) == len(artifact["scale"]) == len(artifact["coefficients"]):
        raise ValueError("Invalid model dimensions.")
    n_meta = artifact["meta_feature_count"]
    vocab = artifact["text_vocabulary"]
    if (type(n_meta) is not int or not 0 < n_meta < len(names)
            or names[n_meta:] != [f"text:{term}" for term in vocab]
            or len(vocab) != len(artifact["text_idf"]) or len(vocab) != len(set(vocab))):
        raise ValueError("Invalid model text feature contract.")
    values = artifact["coefficients"] + artifact["scale"] + [
        artifact[k] for k in ("intercept", "calibration_slope", "calibration_intercept")
    ] + artifact["text_idf"]
    if not all(type(v) in (float, int) and math.isfinite(v) for v in values):
        raise ValueError("Model contains invalid numeric parameters.")
    if any(s <= 0 for s in artifact["scale"]):
        raise ValueError("Model scale must be positive.")
    if not timestamp(artifact["train_until"]) < timestamp(artifact["calibrate_until"]) < timestamp(artifact["as_of"]):
        raise ValueError("Invalid model temporal boundaries.")
    return artifact


def load_artifact(path: str) -> dict | None:
    if not path:
        return None
    return validate_artifact(json.loads(Path(path).read_text()))


def predict(row: dict, artifact: dict | None) -> dict:
    validate_snapshot(row)
    study = row["study"]
    reasons = eligibility(study)
    f = expanded_features(study)
    if artifact is None:
        reasons.append("A trained and evaluated model has not been configured.")
    else:
        validate_artifact(artifact)
        if artifact["status"] != "research_candidate":
            reasons.append("The model did not pass held-out evaluation against the baselines.")
        if phase(study) not in artifact["supported_phases"]:
            reasons.append("This phase was not represented in the training cohort.")
        if row["nct_id"] in {nct for group in artifact["splits"].values() for nct in group["nct_ids"]}:
            reasons.append("This trial belongs to a development or evaluation cohort.")
        if timestamp(row["retrieved_at"]) <= timestamp(artifact["as_of"]):
            reasons.append("A snapshot newer than the model's evaluation cutoff is required.")
        unknown = [key for key in f if "=" in key and f"design:{key}" not in artifact["feature_names"]]
        if unknown:
            reasons.append("Study design categories were not represented in model training.")
    text_values, coverage = tfidf_values(protocol_text(study), artifact["text_vocabulary"],
                                         artifact["text_idf"]) if artifact else ([], 0.0)
    result = {"nct_id": row["nct_id"], "target": TARGET,
              "source_url": row["source_url"], "snapshot_at": row["retrieved_at"],
              "snapshot_hash": row["content_hash"], "phase": phase(study),
              "next_phase": TRANSITIONS.get(phase(study)),
              "status": "insufficient_evidence" if reasons else "research_estimate",
              "probability": None, "reasons": reasons,
              "model_id": artifact["model_id"] if artifact else None,
              "drivers": [], "text_vocabulary_coverage": round(coverage, 3),
              "evidence_reliability": None}
    if artifact and coverage < 0.15:
        result["reasons"].append("Trial wording has too little overlap with the training vocabulary.")
        result["status"] = "insufficient_evidence"
    if result["reasons"]:
        return result
    names = artifact["feature_names"]
    n_meta = artifact["meta_feature_count"]
    feature_values = [f.get(name.removeprefix("design:"), 0.0) for name in names[:n_meta]] + text_values
    contributions = [value * coef / scale for value, coef, scale in zip(
        feature_values, artifact["coefficients"], artifact["scale"], strict=True)]
    logit = artifact["calibration_slope"] * (artifact["intercept"] + sum(contributions)) + artifact["calibration_intercept"]
    result["probability"] = 1 / (1 + math.exp(-max(-40, min(40, logit))))
    phase_report = artifact["evaluation"]["by_phase"].get(phase(study), {})
    result["evidence_reliability"] = "moderate" if (
        phase_report.get("n", 0) >= 40 and coverage >= 0.5
    ) else "limited"
    result["drivers"] = sorted([
        {"feature": name, "log_odds_contribution": value * artifact["calibration_slope"]}
        for name, value in zip(artifact["feature_names"], contributions, strict=True) if value
    ], key=lambda d: abs(d["log_odds_contribution"]), reverse=True)[:5]
    return result
