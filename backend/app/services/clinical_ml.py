"""Company-scoped registry snapshot ingestion and model serving."""
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.ml.data import TARGET, digest, snapshot
from app.ml.prediction import load_artifact, predict
from app.models import RawProviderResponse
from app.providers.clinicaltrials import ClinicalTrialsCatalystProvider


def _resource_key(company):
    # Include owner and ticker so recycled numeric IDs cannot recover another cohort.
    return "clinical_ml:" + digest([company.owner_id, company.id, company.ticker])[:48]


def latest_cohort(session, company):
    return session.execute(select(RawProviderResponse).where(
        RawProviderResponse.provider == "clinicaltrials",
        RawProviderResponse.resource_type == "clinical_ml_cohort",
        RawProviderResponse.resource_key == _resource_key(company),
    ).order_by(RawProviderResponse.id.desc()).limit(1)).scalar_one_or_none()


def ingest(session, company, config):
    provider = ClinicalTrialsCatalystProvider(
        user_agent=config["CLINICALTRIALS_USER_AGENT"],
        base_url=config["CLINICALTRIALS_BASE_URL"],
        timeout=config["CLINICALTRIALS_TIMEOUT_SECONDS"],
    )
    batch = provider.fetch_studies(sponsor=company.name,
                                   limit=config["CLINICAL_ML_MAX_STUDIES"])
    observed = datetime.now(UTC).isoformat()
    rows = [snapshot(study, observed, query=f"sponsor:{company.name}") for study in batch.studies]
    payload = {"snapshots": rows, "retrieved_at": observed,
               "truncated": batch.truncated, "query": f"sponsor:{company.name}"}
    # Each successful pull records the full cohort, including an empty result;
    # latest views must not silently fall back to stale or unrelated studies.
    session.add(RawProviderResponse(
        provider="clinicaltrials", resource_type="clinical_ml_cohort",
        resource_key=_resource_key(company), content_hash=digest(payload),
        payload=json.dumps(payload, allow_nan=False),
    ))
    session.commit()
    return {"fetched": len(rows), "truncated": batch.truncated, "retrieved_at": observed}


def view(session, company, config):
    raw = latest_cohort(session, company)
    payload = json.loads(raw.payload) if raw else {}
    model_error = None
    try:
        artifact = load_artifact(config.get("CLINICAL_ML_MODEL_PATH", ""))
    except (OSError, ValueError, TypeError, KeyError):
        artifact = None
        model_error = "The configured model could not be loaded or validated."
    trials = []
    for row in payload.get("snapshots", []):
        protocol = row["study"].get("protocolSection") or {}
        arms = protocol.get("armsInterventionsModule") or {}
        drugs = [i.get("name") for i in arms.get("interventions") or []
                 if i.get("type") in {"DRUG", "BIOLOGICAL"} and i.get("name")]
        trials.append({**predict(row, artifact),
                       "title": (protocol.get("identificationModule") or {}).get("briefTitle"),
                       "interventions": drugs,
                       "conditions": (protocol.get("conditionsModule") or {}).get("conditions") or [],
                       "registry_status": (protocol.get("statusModule") or {}).get("overallStatus"),
                       "company_match": "unverified_sponsor_name"})
    return {"ticker": company.ticker, "target": TARGET,
            "model_status": artifact["status"] if artifact else "not_configured",
            "model_error": model_error, "model_id": artifact["model_id"] if artifact else None,
            "evaluation": artifact["evaluation"] if artifact else None,
            "retrieved_at": payload.get("retrieved_at"),
            "truncated": payload.get("truncated", False), "trials": trials,
            "limitations": [
                "Scores estimate same-indication Phase 1→2 or Phase 2→3 advancement, not endpoint success or drug approval.",
                "The percentage is a calibrated advancement estimate; model reliability is shown separately.",
                "Sponsor matches and intervention roles require verification; comparators may appear in drug names.",
                "Several studies of one program are not combined into a single program estimate.",
            ] + (artifact["limitations"] if artifact else [
                "No validated outcome dataset or trained model is bundled. Predictions remain unavailable."]),
            "ingestion_enabled": config.get("CATALYST_PROVIDER") == "clinicaltrials"}
