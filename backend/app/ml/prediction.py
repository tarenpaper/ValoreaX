"""Dependency-light inference using exactly the offline feature contract."""
import json
import math
from pathlib import Path

from .data import TARGET, digest, eligibility, timestamp, validate_snapshot
from .features import FEATURE_VERSION, expanded_features, phase


def validate_artifact(artifact: dict) -> dict:
    if (artifact.get("artifact_version") != 1 or artifact.get("target") != TARGET
            or artifact.get("feature_version") != FEATURE_VERSION):
        raise ValueError("Unsupported clinical model artifact.")
    if artifact.get("model_id") != digest({k: v for k, v in artifact.items() if k != "model_id"}):
        raise ValueError("Clinical model integrity check failed.")
    names = artifact["feature_names"]
    if not names or len(names) != len(set(names)):
        raise ValueError("Invalid model feature names.")
    if not len(names) == len(artifact["scale"]) == len(artifact["coefficients"]):
        raise ValueError("Invalid model dimensions.")
    values = artifact["coefficients"] + artifact["scale"] + [
        artifact[k] for k in ("intercept", "calibration_slope", "calibration_intercept")]
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
        unknown = [key for key in f if "=" in key and key not in artifact["feature_names"]]
        if unknown:
            reasons.append("Study design categories were not represented in model training.")
    result = {"nct_id": row["nct_id"], "target": TARGET,
              "source_url": row["source_url"], "snapshot_at": row["retrieved_at"],
              "snapshot_hash": row["content_hash"], "phase": phase(study),
              "status": "insufficient_evidence" if reasons else "research_estimate",
              "probability": None, "reasons": reasons,
              "model_id": artifact["model_id"] if artifact else None,
              "drivers": []}
    if reasons:
        return result
    contributions = [f.get(name, 0.0) * coef / scale for name, coef, scale in zip(
        artifact["feature_names"], artifact["coefficients"], artifact["scale"], strict=True)]
    logit = artifact["calibration_slope"] * (artifact["intercept"] + sum(contributions)) + artifact["calibration_intercept"]
    result["probability"] = 1 / (1 + math.exp(-max(-40, min(40, logit))))
    result["drivers"] = sorted([
        {"feature": name, "log_odds_contribution": value * artifact["calibration_slope"]}
        for name, value in zip(artifact["feature_names"], contributions, strict=True) if value
    ], key=lambda d: abs(d["log_odds_contribution"]), reverse=True)[:5]
    return result
