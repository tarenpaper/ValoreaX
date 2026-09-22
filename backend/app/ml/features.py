"""Shared training/serving allowlist. No outcomes, dates, IDs or free-text results."""
import math

FEATURE_VERSION = "trial_design_text_v2"


def phase(study: dict) -> str:
    return "+".join(sorted((study.get("protocolSection", {}).get("designModule") or {})
                           .get("phases") or [])) or "UNKNOWN"


def features(study: dict) -> dict:
    protocol = study.get("protocolSection") or {}
    design = protocol.get("designModule") or {}
    info = design.get("designInfo") or {}
    arms = protocol.get("armsInterventionsModule") or {}
    outcomes = protocol.get("outcomesModule") or {}
    sponsor = (protocol.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}
    enrollment = design.get("enrollmentInfo") or {}
    count = enrollment.get("count")
    planned = (enrollment.get("type") == "ESTIMATED" and type(count) in (int, float)
               and math.isfinite(count) and 0 < count <= 10_000_000)
    result = {
        "phase": phase(study),
        "allocation": info.get("allocation") or "UNKNOWN",
        "intervention_model": info.get("interventionModel") or "UNKNOWN",
        "masking": (info.get("maskingInfo") or {}).get("masking") or "UNKNOWN",
        "primary_purpose": info.get("primaryPurpose") or "UNKNOWN",
        "sponsor_class": sponsor.get("class") or "UNKNOWN",
        "planned_enrollment_log": math.log1p(count) if planned else 0.0,
        "planned_enrollment_missing": float(not planned),
        "arm_count": float(len(arms.get("armGroups") or [])),
        "arms_missing": float(not arms.get("armGroups")),
        "primary_endpoint_count": float(len(outcomes.get("primaryOutcomes") or [])),
        "posted_results_available": float(bool(study.get("resultsSection"))),
    }
    types = {i.get("type") for i in arms.get("interventions") or []}
    result.update({f"intervention_{t.lower()}": float(t in types) for t in ("DRUG", "BIOLOGICAL")})
    return result


def expanded_features(study: dict) -> dict[str, float]:
    return {f"{key}={value}" if isinstance(value, str) else key:
            1.0 if isinstance(value, str) else value for key, value in features(study).items()}
