"""News-view aggregation: one composite payload for the News Intelligence page.

Assembles, for one company: the analyzed article stream, a catalyst→news
correlation matrix (news volume + avg sentiment per pipeline asset, matched by
mention), trending topic tags, an app-wide sector-sentiment roll-up, and the
price series + event markers for the market-reaction chart.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from statistics import mean

from sqlalchemy import nulls_last, select

from app.api.serializers import news_to_dict
from app.models import CatalystEvent, Company, MarketPrice, NewsArticle
from app.services.drug_aliases import expand_aliases
from app.services.news_analysis import clinical_relevance, mentions

_PRICE_POINTS = 40

# Generic disease words excluded from indication matching (too broad to be meaningful).
_GENERIC_INDICATION = {
    "cancer", "cancers", "tumor", "tumors", "tumour", "disease", "diseases",
    "disorder", "disorders", "solid", "metastatic", "advanced", "chronic", "acute",
    "syndrome", "relapsed", "refractory", "stage", "cell", "positive", "negative",
    "mediated", "associated", "related", "condition", "conditions", "malignant",
    "malignancies", "carcinoma", "carcinomas", "neoplasm", "neoplasms", "recurrent",
    "moderate", "severe", "adult", "pediatric", "unresectable", "locally",
    # Over-broad words that appear constantly in general market news.
    "large", "small", "early", "late", "primary", "secondary", "human", "patient",
    "patients", "study", "studies", "trial", "trials", "combination", "therapy",
    "treatment", "phase", "line", "first", "second", "newly", "diagnosed", "high", "type",
}
# Connectors that split a combination therapy into its component drugs.
_DRUG_SPLIT = re.compile(r"\s*(?:/|\+|,|\bwith\b|\bplus\b|\band\b|\bin\b)\s*", re.IGNORECASE)


def _asset_match_terms(drug_program: str | None, indication: str | None) -> list[str]:
    """Terms that tie news to a pipeline asset: the drug program, its component
    drugs (for combinations), and *specific* indication keywords — so a headline
    naming the drug OR the disease counts, without generic words matching everything.
    """
    terms: set[str] = set()
    prog = (drug_program or "").strip()
    drug_parts: set[str] = set()
    if 4 <= len(prog) <= 60:
        drug_parts.add(prog)
    for part in _DRUG_SPLIT.split(prog):
        p = part.strip()
        if len(p) >= 4 and not p.lower().startswith(("a study", "study of", "phase", "the ")):
            drug_parts.add(p)
    terms |= drug_parts
    # Brand ↔ generic aliases (e.g. "enfortumab vedotin" ⇄ "Padcev").
    for part in drug_parts:
        terms |= expand_aliases(part)
    for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", indication or ""):
        if word.lower() not in _GENERIC_INDICATION:
            terms.add(word)
    seen: dict[str, str] = {}
    for t in terms:
        seen.setdefault(t.lower(), t)
    return sorted(seen.values(), key=str.lower)


def _articles(session, company_id: int) -> list[NewsArticle]:
    return session.execute(
        select(NewsArticle)
        .where(NewsArticle.company_id == company_id)
        .order_by(nulls_last(NewsArticle.published_at.desc()))
    ).scalars().all()


def _catalyst_matrix(session, company_id: int, articles: list[NewsArticle]) -> list[dict]:
    catalysts = session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all()
    texts = [f"{a.headline} {a.summary or ''}" for a in articles]

    programs: dict[str, dict] = {}
    for c in catalysts:
        p = programs.setdefault(c.drug_program, {"indication": c.indication, "trials": 0})
        p["trials"] += 1
        if not p["indication"] and c.indication:
            p["indication"] = c.indication

    rows = []
    for prog, info in programs.items():
        terms = _asset_match_terms(prog, info["indication"])
        matched = [
            a for a, text in zip(articles, texts, strict=False)
            if any(mentions(text, term) for term in terms)
        ]
        vol = len(matched)
        avg = round(mean([a.sentiment_score for a in matched]), 3) if matched else 0.0
        confidence = "high" if vol >= 5 else "medium" if vol >= 2 else "low"
        rows.append({
            "asset": prog,
            "indication": info["indication"],
            "news_volume": vol,
            "sentiment_score": avg,
            "confidence": confidence,
            "trial_count": info["trials"],
            "match_terms": terms[:6],
        })
    rows.sort(key=lambda r: (r["news_volume"], abs(r["sentiment_score"])), reverse=True)
    return rows[:12]


def _trending_topics(articles: list[NewsArticle]) -> list[dict]:
    counter: Counter[str] = Counter()
    for a in articles:
        try:
            counter.update(json.loads(a.tags) if a.tags else [])
        except (ValueError, TypeError):
            continue
    return [{"topic": t, "count": n} for t, n in counter.most_common(8)]


def _sector_sentiment(session) -> list[dict]:
    companies = session.execute(select(Company)).scalars().all()
    buckets: dict[str, list[float]] = {}
    for comp in companies:
        arts = session.execute(
            select(NewsArticle.sentiment_score).where(NewsArticle.company_id == comp.id)
        ).scalars().all()
        if not arts:
            continue
        buckets.setdefault(comp.sector or "Unknown", []).extend(arts)
    out = [
        {"sector": sec, "avg_score": round(mean(scores), 3), "count": len(scores)}
        for sec, scores in buckets.items()
    ]
    out.sort(key=lambda r: r["avg_score"], reverse=True)
    return out


def _price_series(session, company_id: int) -> list[dict]:
    prices = session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company_id).order_by(MarketPrice.date)
    ).scalars().all()
    return [{"date": p.date.isoformat(), "close": p.close} for p in prices[-_PRICE_POINTS:]]


def _markers(session, company_id: int, enriched: list[dict], lo: str, hi: str) -> list[dict]:
    """Chart markers: only **clinically relevant** news events, plus catalyst dates."""
    markers: list[dict] = []
    for d in enriched:
        if d["is_clinical"] and d["published_at"]:
            day = d["published_at"][:10]
            if lo <= day <= hi:
                markers.append({
                    "date": day, "label": d["headline"][:60], "kind": "news",
                    "sentiment": d["sentiment"]["label"], "relevance": d["clinical_relevance"],
                })
    for c in session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all():
        d = (c.actual_date or c.expected_date)
        if d and lo <= d.isoformat() <= hi:
            markers.append({"date": d.isoformat(), "label": f"{c.drug_program} · {c.event_type}",
                            "kind": "catalyst", "sentiment": None, "relevance": None})
    markers.sort(key=lambda m: m["date"])
    return markers


def build_news_view(session, company) -> dict:
    articles = _articles(session, company.id)
    labels = Counter(a.sentiment_label for a in articles)
    matrix = _catalyst_matrix(session, company.id, articles)

    # Union of every pipeline asset's match terms → the "names our drugs" signal.
    asset_terms = tuple({term for row in matrix for term in row["match_terms"]})

    # Enrich each article with a clinical-relevance score, then surface clinical
    # articles to the top of the stream (newest-first within each group).
    enriched = []
    for a in articles:
        d = news_to_dict(a)
        score, is_clinical = clinical_relevance(f"{a.headline} {a.summary or ''}", asset_terms)
        d["clinical_relevance"] = score
        d["is_clinical"] = is_clinical
        enriched.append(d)
    enriched.sort(
        key=lambda d: (d["is_clinical"], d["clinical_relevance"], d["published_at"] or ""),
        reverse=True,
    )
    clinical_count = sum(1 for d in enriched if d["is_clinical"])

    # Chart markers use the clinical-scored articles (clinical news only) + catalysts.
    series = _price_series(session, company.id)
    markers = _markers(session, company.id, enriched, series[0]["date"], series[-1]["date"]) if series else []

    return {
        "company": {"id": company.id, "ticker": company.ticker, "name": company.name,
                    "sector": company.sector},
        "as_of": date.today().isoformat(),
        "summary": {
            "total": len(articles),
            "bullish": labels.get("bullish", 0),
            "bearish": labels.get("bearish", 0),
            "neutral": labels.get("neutral", 0),
            "clinical": clinical_count,
        },
        "articles": enriched,
        "catalyst_matrix": matrix,
        "trending_topics": _trending_topics(articles),
        "sector_sentiment": _sector_sentiment(session),
        "price_series": series,
        "markers": markers,
        "disclaimer": (
            "News sentiment/impact/tags are a transparent keyword heuristic (or provider-supplied "
            "where available), not verified analyst sentiment. Educational research, not advice."
        ),
    }
