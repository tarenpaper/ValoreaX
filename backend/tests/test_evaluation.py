"""Tests for the look-ahead-safe signal evaluation service."""
from __future__ import annotations

from datetime import date

from app.models import CatalystEvent, Company, SignalRun
from app.services.evaluation import evaluate_all, evaluate_company


def _company(db, ticker="VALX") -> Company:
    company = Company(ticker=ticker, name=f"{ticker} Therapeutics", source="mock")
    db.session.add(company)
    db.session.commit()
    return company


def _signal(db, company_id, signal, as_of, engine_version="v4"):
    db.session.add(SignalRun(company_id=company_id, signal=signal, as_of_date=as_of,
                             engine_version=engine_version))
    db.session.commit()


def _catalyst(db, company_id, outcome, actual_date):
    db.session.add(CatalystEvent(
        company_id=company_id, drug_program="VLX-1", event_type="phase_readout",
        outcome=outcome, actual_date=actual_date,
    ))
    db.session.commit()


def test_only_outcomes_after_as_of_are_scored(db):
    company = _company(db)
    _signal(db, company.id, "long", date(2026, 1, 1))
    _catalyst(db, company.id, "positive", date(2025, 6, 1))   # BEFORE the signal — ignored
    _catalyst(db, company.id, "positive", date(2026, 6, 1))   # after — scored, agrees

    stats = evaluate_company(db.session, company.id)
    assert stats["evaluated"] == 1
    assert stats["directional_agreement_rate"] == 1.0
    assert stats["details"][0]["resolved_on"] == "2026-06-01"


def test_disagreement_lowers_rate(db):
    company = _company(db)
    _signal(db, company.id, "short", date(2026, 1, 1))
    _catalyst(db, company.id, "positive", date(2026, 6, 1))   # short vs positive → disagree

    stats = evaluate_company(db.session, company.id)
    assert stats["evaluated"] == 1
    assert stats["directional_agreement_rate"] == 0.0
    assert stats["details"][0]["agreement"] is False


def test_no_post_signal_catalyst_yields_none(db):
    company = _company(db)
    _signal(db, company.id, "long", date(2026, 6, 1))
    _catalyst(db, company.id, "positive", date(2026, 1, 1))   # only a PRE-signal outcome

    stats = evaluate_company(db.session, company.id)
    assert stats["evaluated"] == 0
    assert stats["directional_agreement_rate"] is None
    assert "no fabricated" in stats["note"].lower()


def test_uses_first_resolved_after_anchor(db):
    company = _company(db)
    _signal(db, company.id, "long", date(2026, 1, 1))
    _catalyst(db, company.id, "negative", date(2026, 9, 1))   # later
    _catalyst(db, company.id, "positive", date(2026, 3, 1))   # earliest after anchor → used

    stats = evaluate_company(db.session, company.id)
    assert stats["details"][0]["resolved_on"] == "2026-03-01"
    assert stats["directional_agreement_rate"] == 1.0         # long vs first (positive)


def test_evaluate_all_covers_every_company(db):
    a = _company(db, "AAA")
    _company(db, "BBB")   # a second company with no signals
    _signal(db, a.id, "long", date(2026, 1, 1))
    _catalyst(db, a.id, "positive", date(2026, 6, 1))

    results = evaluate_all(db.session)
    tickers = {r["ticker"] for r in results}
    assert {"AAA", "BBB"} <= tickers
    a_result = next(r for r in results if r["ticker"] == "AAA")
    assert a_result["evaluated"] == 1


def test_agreement_is_reported_per_engine_version(db):
    """A v3 score and a v4 score do not mean the same thing, so they are not pooled."""
    company = _company(db)
    _signal(db, company.id, "long", date(2026, 1, 1), engine_version="v3")
    _signal(db, company.id, "short", date(2026, 1, 1), engine_version="v4")
    _catalyst(db, company.id, "positive", date(2026, 6, 1))

    stats = evaluate_company(db.session, company.id)
    assert stats["directional_agreement_rate"] == 0.5          # pooled, kept for compatibility
    by_version = stats["by_engine_version"]
    assert by_version["v3"]["directional_agreement_rate"] == 1.0
    assert by_version["v4"]["directional_agreement_rate"] == 0.0
    assert "by_engine_version" in stats["note"] or "engine versions" in stats["note"]
