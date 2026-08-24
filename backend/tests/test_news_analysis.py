"""Unit tests for the transparent news heuristics (pure, no I/O)."""
from __future__ import annotations

from app.services.news_analysis import (
    classify_impact,
    clinical_relevance,
    extract_tags,
    heuristic_sentiment,
    mentions,
)


def test_clinical_relevance():
    score, clinical = clinical_relevance("FDA grants Phase 3 trial readout for the therapy")
    assert clinical is True and score > 0
    # Naming a pipeline asset alone qualifies.
    score2, clinical2 = clinical_relevance("Enzalutamide combo update", asset_terms=("enzalutamide",))
    assert clinical2 is True and score2 >= 0.6
    # Generic market chatter is not clinical.
    _, clinical3 = clinical_relevance("Large-cap stock rallies on macro optimism today")
    assert clinical3 is False


def test_sentiment_bullish():
    label, score = heuristic_sentiment("FDA grants Fast Track designation; approval expected")
    assert label == "bullish"
    assert score > 0


def test_sentiment_bearish():
    label, score = heuristic_sentiment("Company receives Complete Response Letter; shares plunge")
    assert label == "bearish"
    assert score < 0


def test_sentiment_neutral_when_no_keywords():
    label, score = heuristic_sentiment("Company files routine document with regulator")
    assert label == "neutral"
    assert score == 0.0


def test_impact_tiers():
    assert classify_impact("SEC", "FDA approval granted; fast track") == "critical"
    assert classify_impact("Reuters", "sector rotation continues in biotech markets today") == "high"
    assert classify_impact("Blog", "a quiet uneventful trading session with little movement seen") == "medium"


def test_extract_tags():
    tags = extract_tags("FDA grants Fast Track; PDUFA date set for the therapy approval")
    assert "Fast Track" in tags
    assert "PDUFA" in tags
    assert "FDA" in tags
    assert "Approval" in tags


def test_mentions_respects_word_boundaries():
    assert mentions("Vertex VX-548 Phase 3 data", "VX-548") is True
    assert mentions("Vertex VX-5480 data", "VX-548") is False
    assert mentions("no ticker here", "VX-548") is False
