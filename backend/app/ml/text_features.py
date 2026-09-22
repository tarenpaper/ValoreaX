"""Versioned public trial text available before the advancement decision."""
import math
import re
from collections import Counter
from html import unescape

TOKEN_PATTERN = re.compile(r"(?u)\b\w\w+\b")
TEXT_LIMIT = 20_000


def protocol_text(study: dict) -> str:
    """Allowlist protocol and posted-result language from one timestamped snapshot.

    Excludes registry status, sponsor conclusions, news, and later-stage records.
    Snapshot time must precede the independently adjudicated transition event.
    """
    protocol = study.get("protocolSection") or {}
    desc = protocol.get("descriptionModule") or {}
    outcomes = protocol.get("outcomesModule") or {}
    eligibility = protocol.get("eligibilityModule") or {}
    conditions = protocol.get("conditionsModule") or {}
    parts = []
    for value in (desc.get("briefSummary"), desc.get("detailedDescription"),
                  eligibility.get("eligibilityCriteria")):
        if isinstance(value, str):
            parts.append(value)
    for outcome in (outcomes.get("primaryOutcomes") or [])[:10]:
        for field in ("measure", "description", "timeFrame"):
            value = outcome.get(field)
            if isinstance(value, str):
                parts.append(value)
    for condition in (conditions.get("conditions") or [])[:10]:
        if isinstance(condition, str):
            parts.append(condition)
    results = study.get("resultsSection") or {}
    measures = (results.get("outcomeMeasuresModule") or {}).get("outcomeMeasures") or []
    for measure in [m for m in measures if m.get("type") == "PRIMARY"][:5]:
        for field in ("title", "description", "populationDescription"):
            value = measure.get(field)
            if isinstance(value, str):
                parts.append(value)
        for analysis in (measure.get("analyses") or [])[:5]:
            for field in ("pValue", "paramValue", "statisticalMethod", "statisticalComment"):
                value = analysis.get(field)
                if isinstance(value, str):
                    parts.append(value)
        for group in (measure.get("classes") or [])[:5]:
            for category in (group.get("categories") or [])[:5]:
                for measurement in (category.get("measurements") or [])[:10]:
                    value = measurement.get("value")
                    if isinstance(value, (str, int, float)):
                        parts.append(str(value))
    text = unescape(" ".join(parts))
    text = re.sub(r"<[^>]*>", " ", text)
    return " ".join(text.split())[:TEXT_LIMIT]


def terms(text: str) -> list[str]:
    tokens = TOKEN_PATTERN.findall(text.lower())
    return tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False)]


def tfidf_values(text: str, vocabulary: list[str], idf: list[float]) -> tuple[list[float], float]:
    """Match sklearn's word (1,2)-gram, sublinear-TF, smoothed-IDF, L2 transform."""
    counts = Counter(terms(text))
    raw = [(1 + math.log(counts[term])) * weight if counts[term] else 0.0
           for term, weight in zip(vocabulary, idf, strict=True)]
    norm = math.sqrt(sum(value * value for value in raw))
    values = [value / norm for value in raw] if norm else raw
    all_terms = sum(counts.values())
    known_terms = sum(counts[term] for term in vocabulary)
    return values, known_terms / all_terms if all_terms else 0.0
