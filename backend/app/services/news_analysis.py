"""Transparent, keyword-based news analysis (sentiment / impact / topic tags).

This is a deliberately simple **heuristic**, not an ML model or a verified analyst
view — every value it produces is labeled ``method="heuristic"`` downstream so it
is never mistaken for real sentiment. When a provider supplies its own sentiment,
that is used instead (and labeled ``method="provider"``).
"""
from __future__ import annotations

import re

_BULLISH = [
    "approval", "approved", "fast track", "breakthrough", "priority review",
    "orphan drug", "positive", "beats", "beat", "tops", "grants", "granted",
    "met primary", "met the primary", "success", "successful", "expands",
    "expansion", "partnership", "collaboration", "licensing", "acquire",
    "acquisition", "milestone", "upgrade", "outperform", "strong", "surge",
    "jump", "rally", "raises guidance", "wins",
]
_BEARISH = [
    "complete response letter", "crl", "reject", "rejected", "fail", "failed",
    "failure", "miss", "missed", "halt", "halted", "discontinue", "discontinued",
    "terminate", "terminated", "lawsuit", "litigation", "recall", "decline",
    "cuts", "downgrade", "delay", "delayed", "warning letter", "safety concern",
    "adverse", "death", "plunge", "drop", "slump", "investigation", "subpoena",
    "patent cliff", "generic competition",
]

# Topic tag -> substrings that imply it.
_TAGS: dict[str, tuple[str, ...]] = {
    "Fast Track": ("fast track",),
    "Breakthrough": ("breakthrough",),
    "PDUFA": ("pdufa",),
    "Approval": ("approv",),
    "CRL": ("crl", "complete response"),
    "Phase 3": ("phase 3", "phase iii"),
    "M&A": ("acquisition", "acquire", "merger", "buyout", "takeover"),
    "Earnings": ("earnings", "quarter", "guidance", "revenue"),
    "Patent": ("patent",),
    "FDA": ("fda",),
    "Orphan Drug": ("orphan",),
    "Partnership": ("partnership", "collaboration", "licensing"),
    "Lawsuit": ("lawsuit", "litigation", "settlement"),
}

_HIGH_IMPACT = ("fda", "approval", "crl", "complete response", "fast track",
                "breakthrough", "pdufa", "phase 3", "acquisition", "merger", "orphan")
_AUTHORITATIVE = {"sec", "fda", "bloomberg", "reuters", "wall street journal", "wsj", "the wall street journal"}


def _count(text: str, terms: list[str]) -> int:
    return sum(1 for t in terms if t in text)


def heuristic_sentiment(text: str) -> tuple[str, float]:
    """Return (label, score in [-1, 1]) from bullish/bearish keyword balance."""
    t = (text or "").lower()
    bull = _count(t, _BULLISH)
    bear = _count(t, _BEARISH)
    total = bull + bear
    if total == 0:
        return "neutral", 0.0
    score = round((bull - bear) / total, 3)
    if score > 0.15:
        return "bullish", score
    if score < -0.15:
        return "bearish", score
    return "neutral", score


def classify_impact(source: str | None, text: str) -> str:
    """Coarse impact tier from source authority + high-impact keywords."""
    t = (text or "").lower()
    src = (source or "").lower()
    hits = _count(t, list(_HIGH_IMPACT))
    authoritative = any(a in src for a in _AUTHORITATIVE)
    if hits >= 2 or (authoritative and hits >= 1):
        return "critical"
    if hits == 1 or authoritative:
        return "high"
    if len(t) < 40:
        return "low"
    return "medium"


def extract_tags(text: str) -> list[str]:
    t = (text or "").lower()
    return [tag for tag, needles in _TAGS.items() if any(n in t for n in needles)]


def mentions(text: str, phrase: str) -> bool:
    """Whole-word-ish mention test used to tie news to a pipeline asset."""
    if not phrase:
        return False
    return re.search(rf"(?<![\w-]){re.escape(phrase.lower())}(?![\w-])", (text or "").lower()) is not None


# Signals that an article is about clinical development / regulatory events.
_CLINICAL = (
    "fda", "phase 1", "phase 2", "phase 3", "phase i", "phase ii", "phase iii",
    "clinical trial", "clinical", "trial", "pdufa", "approval", "approved",
    "breakthrough", "fast track", "complete response", "crl", "readout", "topline",
    "endpoint", "efficacy", "safety", "orphan", "adcomm", "pivotal", "candidate",
    "therapy", "therapeutic", "oncology", "indication", "enrollment", "dosing",
    "cohort", "biologic", "marketing authorization", "label expansion",
    "priority review", "investigational", "drug",
)


def clinical_relevance(text: str, asset_terms: tuple[str, ...] = ()) -> tuple[float, bool]:
    """Score how clinical-trial-relevant an article is → (score 0..1, is_clinical).

    Naming one of the company's own pipeline assets is the strongest signal; a
    couple of generic clinical/regulatory keywords also qualifies. Transparent
    heuristic, surfaced (not hidden) and never presented as verified relevance.
    """
    t = (text or "").lower()
    hits = sum(1 for k in _CLINICAL if k in t)
    asset_hit = any(mentions(t, term) for term in asset_terms)
    score = min(1.0, hits * 0.18 + (0.6 if asset_hit else 0.0))
    is_clinical = asset_hit or hits >= 2
    return round(score, 3), is_clinical
