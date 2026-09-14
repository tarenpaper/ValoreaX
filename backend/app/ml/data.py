"""Auditable registry snapshots and strict, point-in-time outcome joins."""
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlparse

TARGET = "primary_endpoint_success"
SNAPSHOT_VERSION = 1
ACTIVE = {"NOT_YET_RECRUITING", "RECRUITING", "ENROLLING_BY_INVITATION",
          "ACTIVE_NOT_RECRUITING"}


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamps must be ISO-8601 strings with a timezone.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone, e.g. 2024-01-01T00:00:00Z.")
    return parsed.astimezone(UTC)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def snapshot(study: dict, retrieved_at: str, *, query: str = "") -> dict:
    """Retrieval time is evidence availability; never backdate to a registry event."""
    timestamp(retrieved_at)
    nct = study.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
    if not isinstance(nct, str) or not re.fullmatch(r"NCT\d{8}", nct):
        raise ValueError("A snapshot requires a valid NCT identifier.")
    return {"schema_version": SNAPSHOT_VERSION, "nct_id": nct,
            "retrieved_at": retrieved_at, "source": "clinicaltrials.gov",
            "source_url": f"https://clinicaltrials.gov/study/{nct}",
            "query": query, "content_hash": digest(study), "study": study}


def validate_snapshot(row: dict) -> dict:
    expected = snapshot(row["study"], row["retrieved_at"])
    if any(row.get(key) != expected[key] for key in (
        "schema_version", "nct_id", "source", "source_url", "content_hash"
    )):
        raise ValueError("Snapshot identity, source, schema or content hash is invalid.")
    if timestamp(row["retrieved_at"]) > datetime.now(UTC):
        raise ValueError("Snapshot retrieval time cannot be in the future.")
    return row


def eligibility(study: dict) -> list[str]:
    protocol = study.get("protocolSection") or {}
    design = protocol.get("designModule") or {}
    status = protocol.get("statusModule") or {}
    interventions = (protocol.get("armsInterventionsModule") or {}).get("interventions") or []
    reasons = []
    if design.get("studyType") != "INTERVENTIONAL":
        reasons.append("Only interventional trials are supported.")
    if not any(i.get("type") in {"DRUG", "BIOLOGICAL"} for i in interventions):
        reasons.append("No drug or biological intervention is registered.")
    phases = design.get("phases") or []
    if not phases or not set(phases) <= {"PHASE1", "PHASE2", "PHASE3"}:
        reasons.append("The model covers phase 1–3 drug trials.")
    if status.get("overallStatus") not in ACTIVE:
        reasons.append("This snapshot is not an active trial awaiting an outcome.")
    if study.get("hasResults") or study.get("resultsSection") or status.get("resultsFirstPostDateStruct"):
        reasons.append("Results are already present in this snapshot.")
    if not (protocol.get("outcomesModule") or {}).get("primaryOutcomes"):
        reasons.append("Primary endpoints are missing.")
    return reasons


def validate_label(label: dict) -> dict:
    """Labels are adjudications, not registry statuses or catalyst sentiment."""
    if label.get("target") != TARGET:
        raise ValueError(f"Label target must be {TARGET}.")
    if type(label.get("outcome")) is not int or label["outcome"] not in (0, 1):
        raise ValueError("Outcome must be integer 0 or 1; ambiguous outcomes stay unlabeled.")
    if not re.fullmatch(r"NCT\d{8}", str(label.get("nct_id", ""))):
        raise ValueError("Label requires a valid NCT identifier.")
    for key in ("drug_group", "reviewer", "rationale", "source_url"):
        if not isinstance(label.get(key), str) or not label[key].strip():
            raise ValueError(f"Label requires {key}.")
    source = urlparse(label["source_url"])
    if source.scheme not in ("https", "http") or not source.netloc:
        raise ValueError("Label source must be an HTTP(S) evidence URL.")
    prediction, event, known, reviewed = [timestamp(label.get(k)) for k in (
        "prediction_at", "outcome_at", "known_at", "reviewed_at")]
    if not prediction < event <= known <= reviewed:
        raise ValueError("Require prediction_at < outcome_at <= known_at <= reviewed_at.")
    return {**label, "drug_group": label["drug_group"].strip().casefold()}


def build_dataset(snapshots: list[dict], labels: list[dict], as_of: str):
    """One trial per dataset. Earliest known eligible data is not invented from latest data."""
    cutoff = timestamp(as_of)
    by_nct = {}
    versions = {}
    for row in snapshots:
        validate_snapshot(row)
        key = (row["nct_id"], timestamp(row["retrieved_at"]))
        if key in versions and versions[key] != row["content_hash"]:
            raise ValueError("Conflicting snapshot versions share the same retrieval time.")
        versions[key] = row["content_hash"]
        by_nct.setdefault(row["nct_id"], []).append(row)
    rows, excluded, seen = [], Counter(), set()
    for item in labels:
        label = validate_label(item)
        nct = label["nct_id"]
        if nct in seen:
            raise ValueError(f"Duplicate labels for {nct}; adjudicate to one outcome first.")
        seen.add(nct)
        if timestamp(label["reviewed_at"]) > cutoff:
            excluded["label_not_available_as_of"] += 1
            continue
        candidates = [s for s in by_nct.get(nct, [])
                      if timestamp(s["retrieved_at"]) <= timestamp(label["prediction_at"])]
        if not candidates:
            excluded["no_snapshot_before_prediction"] += 1
            continue
        selected = max(candidates, key=lambda s: timestamp(s["retrieved_at"]))
        if eligibility(selected["study"]):
            excluded["ineligible_snapshot"] += 1
            continue
        rows.append({"label": label, "snapshot": selected})
    return sorted(rows, key=lambda r: (timestamp(r["label"]["prediction_at"]),
                                      r["label"]["nct_id"])), dict(excluded)
