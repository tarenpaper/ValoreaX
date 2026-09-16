"""Tests for the transparent signal engine."""
from __future__ import annotations

from app.services.signals import (
    BASIS_MANUAL,
    BASIS_OWN_RANGE,
    BASIS_PEER,
    CONFIDENCE_FLOOR,
    LONG_THRESHOLD,
    SHORT_THRESHOLD,
    W_ANALYST,
    SignalInputs,
    score_signal,
)


def component(result, name):
    return next((c for c in result.components if c["name"] == name), None)


def test_strong_bullish_inputs_yield_long():
    res = score_signal(SignalInputs(
        valuation_upside=0.40, catalyst_outcome="positive", event_type="pdufa",
        days_to_next_catalyst=20, abnormal_return=0.10, cash_runway_quarters=10,
        manual_confidence=0.9,
    ))
    assert res.signal == "long"
    assert res.score >= LONG_THRESHOLD
    assert 0 <= res.confidence <= 1


def test_strong_bearish_inputs_yield_short():
    res = score_signal(SignalInputs(
        valuation_upside=-0.40, catalyst_outcome="negative", event_type="crl",
        abnormal_return=-0.15, cash_runway_quarters=1.0, manual_confidence=0.9,
    ))
    assert res.signal == "short"
    assert res.score <= SHORT_THRESHOLD


def test_neutral_inputs_yield_watchlist():
    res = score_signal(SignalInputs(
        valuation_upside=0.02, catalyst_outcome="pending", event_type="pdufa",
        abnormal_return=0.0, cash_runway_quarters=6, manual_confidence=0.9,
    ))
    assert res.signal == "watchlist"


def test_low_confidence_forces_watchlist_even_with_high_score():
    # Only one input present and no manual confidence -> confidence below floor.
    res = score_signal(SignalInputs(valuation_upside=0.5))
    assert res.confidence < CONFIDENCE_FLOOR
    assert res.signal == "watchlist"
    assert "floor" in res.rationale.lower()


def test_high_impact_event_amplifies_catalyst_contribution():
    # Use a non-saturating outcome ('mixed', factor -0.3) so the ×1.2 high-impact
    # multiplier is visible; a fully 'positive' outcome already hits the cap.
    high = score_signal(SignalInputs(catalyst_outcome="mixed", event_type="pdufa",
                                     valuation_upside=0.0, manual_confidence=1.0))
    low = score_signal(SignalInputs(catalyst_outcome="mixed", event_type="other",
                                    valuation_upside=0.0, manual_confidence=1.0))
    high_c = next(c for c in high.components if c["name"] == "catalyst_outcome")
    low_c = next(c for c in low.components if c["name"] == "catalyst_outcome")
    assert abs(high_c["contribution"]) > abs(low_c["contribution"])


def test_positive_outcome_saturates_component_cap():
    res = score_signal(SignalInputs(catalyst_outcome="positive", event_type="pdufa",
                                    valuation_upside=0.0, manual_confidence=1.0))
    catalyst = next(c for c in res.components if c["name"] == "catalyst_outcome")
    assert catalyst["contribution"] == catalyst["weight"]  # capped, never exceeds weight


def test_contributions_sum_to_score():
    res = score_signal(SignalInputs(
        valuation_upside=0.2, catalyst_outcome="mixed", event_type="adcomm",
        abnormal_return=0.05, cash_runway_quarters=2, manual_confidence=0.6,
    ))
    total = round(sum(c["contribution"] for c in res.components), 2)
    assert total == res.score


def test_rationale_lists_every_component():
    inputs = SignalInputs(valuation_upside=0.2, catalyst_outcome="positive",
                          abnormal_return=0.05, cash_runway_quarters=5, manual_confidence=0.8)
    res = score_signal(inputs)
    # One explanation line per component plus a final decision line.
    assert len(res.rationale.splitlines()) == len(res.components) + 1


def test_more_inputs_increase_confidence():
    few = score_signal(SignalInputs(valuation_upside=0.2, manual_confidence=1.0))
    many = score_signal(SignalInputs(
        valuation_upside=0.2, catalyst_outcome="positive",
        abnormal_return=0.05, cash_runway_quarters=6, manual_confidence=1.0,
    ))
    assert many.confidence > few.confidence


def test_missing_inputs_are_simply_skipped():
    res = score_signal(SignalInputs(valuation_upside=0.3, manual_confidence=1.0))
    names = {c["name"] for c in res.components}
    assert names == {"valuation"}


def test_analyst_consensus_bullish_contributes_positively():
    res = score_signal(SignalInputs(analyst_consensus=1.0, analyst_label="Strong Buy",
                                    manual_confidence=1.0))
    comp = next(c for c in res.components if c["name"] == "analyst_consensus")
    assert comp["contribution"] == W_ANALYST          # +1 tilt saturates the weight
    assert "Strong Buy" in comp["explanation"]


def test_analyst_consensus_bearish_is_negative():
    res = score_signal(SignalInputs(analyst_consensus=-0.8, manual_confidence=1.0))
    comp = next(c for c in res.components if c["name"] == "analyst_consensus")
    assert comp["contribution"] < 0


def test_component_weights_sum_to_100():
    from app.services import signals
    weights = (signals.W_VALUATION, signals.W_CATALYST, signals.W_EXCLUSIVITY,
               signals.W_FINANCIAL_HEALTH, signals.W_ANALYST, signals.W_ABNORMAL_RETURN,
               signals.W_NEWS)
    assert sum(weights) == 100.0


# --- Valuation: relative, because sum-of-the-parts has no terminal value ------------
def test_a_multiple_below_the_peer_premium_is_bullish():
    """SOTP omits terminal value, so every multiple is >1x; only the deviation informs."""
    result = score_signal(SignalInputs(valuation_multiple=1.7, valuation_reference=2.4,
                                       valuation_basis=BASIS_PEER,
                                       valuation_basis_detail="3 valued companies"))
    entry = component(result, "valuation")
    assert entry["contribution"] > 0 and entry["basis"] == BASIS_PEER
    assert "1.70x" in entry["explanation"].replace("×", "x")
    assert "3 valued companies" in entry["explanation"]

    # The same absolute multiple is bearish when peers trade cheaper.
    expensive = score_signal(SignalInputs(valuation_multiple=1.7, valuation_reference=1.2,
                                          valuation_basis=BASIS_PEER))
    assert component(expensive, "valuation")["contribution"] < 0


def test_a_manual_upside_overrides_any_multiple():
    result = score_signal(SignalInputs(valuation_upside=0.40, valuation_multiple=9.0,
                                       valuation_reference=1.0, valuation_basis=BASIS_PEER))
    entry = component(result, "valuation")
    assert entry["basis"] == BASIS_MANUAL and entry["contribution"] > 0


def test_own_range_basis_says_it_reads_as_mean_reversion():
    result = score_signal(SignalInputs(valuation_multiple=1.5, valuation_reference=2.0,
                                       valuation_basis=BASIS_OWN_RANGE,
                                       valuation_basis_detail="62 daily closes"))
    assert "mean reversion" in component(result, "valuation")["explanation"]


def test_valuation_is_absent_without_a_multiple_or_an_upside():
    result = score_signal(SignalInputs(catalyst_outcome="pending"))
    assert component(result, "valuation") is None
    assert any(s["name"] == "valuation" for s in result.skipped)


# --- Exclusivity: the patent cliff the other components cannot see ------------------
def test_a_near_exclusivity_cliff_scores_negative():
    near = score_signal(SignalInputs(exclusivity_years=2.0))
    far = score_signal(SignalInputs(exclusivity_years=12.0))
    assert component(near, "exclusivity_runway")["contribution"] < 0
    assert component(far, "exclusivity_runway")["contribution"] > 0


def test_pipeline_value_softens_a_cliff_but_never_hurts():
    bare = score_signal(SignalInputs(exclusivity_years=4.0))
    with_pipeline = score_signal(SignalInputs(exclusivity_years=4.0, pipeline_value_share=0.5))
    assert (component(with_pipeline, "exclusivity_runway")["contribution"]
            > component(bare, "exclusivity_runway")["contribution"])
    assert "pipeline carries 50%" in component(with_pipeline, "exclusivity_runway")["explanation"]


def test_exclusivity_is_absent_when_no_drug_is_valued():
    result = score_signal(SignalInputs(analyst_consensus=0.5))
    assert component(result, "exclusivity_runway") is None


# --- Financial health: stage-aware, using whatever the filings support --------------
def test_low_runway_is_a_financing_risk():
    result = score_signal(SignalInputs(cash_runway_quarters=1.0))
    entry = component(result, "financial_health")
    assert entry["contribution"] < 0 and "financing risk" in entry["explanation"]


def test_a_cash_generative_company_is_judged_on_margin_instead_of_runway():
    """No meaningful runway means no burn to divide by, so margin stands in."""
    result = score_signal(SignalInputs(fcf_margin=0.27))
    entry = component(result, "financial_health")
    assert entry["contribution"] > 0 and "free cash flow margin" in entry["explanation"]


def test_dilution_counts_against_a_company_at_any_stage():
    diluting = score_signal(SignalInputs(cash_runway_quarters=10, dilution_yoy=0.25))
    steady = score_signal(SignalInputs(cash_runway_quarters=10, dilution_yoy=-0.01))
    assert (component(diluting, "financial_health")["contribution"]
            < component(steady, "financial_health")["contribution"])


def test_financial_health_averages_the_figures_that_exist():
    entry = component(score_signal(SignalInputs(cash_runway_quarters=10, dilution_yoy=0.0)),
                      "financial_health")
    assert entry["input_value"]["runway_quarters"] == 10
    assert entry["input_value"]["fcf_margin"] is None


# --- News: high-impact only, and labelled as the heuristic it is --------------------
def test_news_sentiment_moves_the_score_but_only_a_little():
    result = score_signal(SignalInputs(news_sentiment=1.0, news_article_count=4))
    entry = component(result, "news_sentiment")
    assert entry["contribution"] == 5.0
    assert "heuristic" in entry["explanation"] and "4 high-impact articles" in entry["explanation"]


def test_news_alone_can_never_reach_a_directional_verdict():
    result = score_signal(SignalInputs(news_sentiment=1.0, news_article_count=9,
                                       manual_confidence=1.0))
    assert result.signal == "watchlist"


def test_news_is_absent_when_nothing_qualified():
    assert component(score_signal(SignalInputs(news_article_count=0)), "news_sentiment") is None


# --- Confidence --------------------------------------------------------------------
def test_value_concentrated_in_one_drug_lowers_confidence_not_direction():
    spread = score_signal(SignalInputs(valuation_upside=0.4, catalyst_outcome="positive",
                                       value_concentration=0.30))
    concentrated = score_signal(SignalInputs(valuation_upside=0.4, catalyst_outcome="positive",
                                             value_concentration=0.89,
                                             top_asset_name="TRIKAFTA/KAFTRIO"))
    assert concentrated.score == spread.score
    assert concentrated.confidence < spread.confidence
    assert any("TRIKAFTA/KAFTRIO" in w for w in concentrated.warnings)


def test_skipped_components_state_why_they_are_missing():
    result = score_signal(SignalInputs(analyst_consensus=0.5))
    missing = {entry["name"]: entry["reason"] for entry in result.skipped}
    assert "analyst_consensus" not in missing
    assert "No high-impact article" in missing["news_sentiment"]
    assert missing["exclusivity_runway"]


# --- Choosing the reference, against the stored workspace ---------------------------
def _valued_company(db, ticker, base_revenue, close, owner="owner-1"):
    """A company with one marketed drug and a price, so it has a price ÷ SOTP multiple."""
    import json
    from datetime import date, timedelta

    from app.models import Company, DrugAsset, FinancialMetric, MarketPrice
    company = Company(ticker=ticker, name=f"{ticker} Bio", source="mock", owner_id=owner)
    db.session.add(company)
    db.session.flush()
    db.session.add(DrugAsset(
        company_id=company.id, key="drug", name="Drug", kind="marketed",
        origin="sec_product_line",
        extracted=json.dumps({"base_revenue": base_revenue, "loe_year": 2040, "fiscal_year": 2025}),
    ))
    db.session.add(FinancialMetric(
        company_id=company.id, concept="shares_outstanding", value=100e6, unit="shares",
        fiscal_year=2025, source="mock", status="reported"))
    for offset in range(40):
        db.session.add(MarketPrice(company_id=company.id,
                                   date=date.today() - timedelta(days=offset),
                                   close=close, source="mock"))
    db.session.commit()
    return company


def test_the_reference_is_the_peer_median_once_enough_companies_are_valued(db):
    """SOTP sits below price everywhere, so the premium peers carry is the yardstick."""
    from app.services.derivations import derive_valuation_signal_inputs

    cheap = _valued_company(db, "CHEAP", base_revenue=900e6, close=40.0)
    _valued_company(db, "MID", base_revenue=900e6, close=80.0)
    _valued_company(db, "RICH", base_revenue=900e6, close=160.0)

    derived = derive_valuation_signal_inputs(db.session, cheap)
    assert derived["valuation_basis"] == BASIS_PEER
    assert "3 valued companies" in derived["valuation_basis_detail"]
    # Same drug, same share count: the median multiple is the middle company's.
    assert derived["valuation_multiple"] < derived["valuation_reference"]

    entry = component(score_signal(SignalInputs(**derived)), "valuation")
    assert entry["contribution"] > 0 and "below the peer median" in entry["explanation"]


def test_a_thin_workspace_falls_back_to_the_company_s_own_range(db):
    """Two companies cannot supply a meaningful median, so the basis changes and says so."""
    from app.services.derivations import derive_valuation_signal_inputs

    alone = _valued_company(db, "ALONE", base_revenue=900e6, close=40.0)
    _valued_company(db, "OTHER", base_revenue=900e6, close=80.0)

    derived = derive_valuation_signal_inputs(db.session, alone)
    assert derived["valuation_basis"] == BASIS_OWN_RANGE
    assert "daily closes" in derived["valuation_basis_detail"]


def test_another_account_s_companies_never_enter_the_peer_set(db):
    from app.services.derivations import peer_valuation_multiples

    mine = _valued_company(db, "MINE", base_revenue=900e6, close=40.0, owner="owner-1")
    _valued_company(db, "THEIRS", base_revenue=900e6, close=80.0, owner="owner-2")
    assert set(peer_valuation_multiples(db.session, mine)) == {"MINE"}


# --- The own-range basis must not read a market move as company-specific ------------
def _priced_company(db, ticker, base_revenue, closes, benchmark=None, symbol="XLV"):
    """A valued company whose price series is `closes`, oldest first, one per day."""
    import json
    from datetime import date, timedelta

    from app.models import BenchmarkPrice, Company, DrugAsset, FinancialMetric, MarketPrice
    company = Company(ticker=ticker, name=f"{ticker} Bio", source="mock", owner_id="solo")
    db.session.add(company)
    db.session.flush()
    db.session.add(DrugAsset(
        company_id=company.id, key="drug", name="Drug", kind="marketed",
        origin="sec_product_line",
        extracted=json.dumps({"base_revenue": base_revenue, "loe_year": 2040, "fiscal_year": 2025}),
    ))
    db.session.add(FinancialMetric(
        company_id=company.id, concept="shares_outstanding", value=100e6, unit="shares",
        fiscal_year=2025, source="mock", status="reported"))
    start = date.today() - timedelta(days=len(closes) - 1)
    for offset, close in enumerate(closes):
        day = start + timedelta(days=offset)
        db.session.add(MarketPrice(company_id=company.id, date=day, close=close, source="mock"))
        if benchmark is not None:
            db.session.add(BenchmarkPrice(symbol=symbol, date=day, close=benchmark[offset],
                                          source="mock"))
    db.session.commit()
    return company


def _ramp(start, end, n=40):
    step = (end - start) / (n - 1)
    return [start + step * i for i in range(n)]


def test_a_market_wide_rally_is_not_read_as_the_company_getting_expensive(db):
    """The move momentum reports as nothing company-specific must not score as expensive."""
    from app.services.derivations import derive_valuation_signal_inputs

    # Company and benchmark both double: the company merely tracked the market.
    company = _priced_company(db, "TRACK", 900e6, _ramp(50, 100), benchmark=_ramp(200, 400))
    derived = derive_valuation_signal_inputs(db.session, company, benchmark_symbol="XLV")

    assert derived["valuation_basis"] == BASIS_OWN_RANGE
    assert "carried at XLV" in derived["valuation_basis_detail"]
    entry = component(score_signal(SignalInputs(**derived)), "valuation")
    assert abs(entry["contribution"]) < 1.0, entry["explanation"]


def test_a_company_specific_rally_still_reads_as_expensive(db):
    """With the benchmark flat, outrunning it is genuinely a richer multiple."""
    from app.services.derivations import derive_valuation_signal_inputs

    company = _priced_company(db, "SOLO", 900e6, _ramp(50, 100), benchmark=[200.0] * 40)
    derived = derive_valuation_signal_inputs(db.session, company, benchmark_symbol="XLV")
    assert component(score_signal(SignalInputs(**derived)), "valuation")["contribution"] < -5


def test_without_benchmark_history_the_reference_says_it_is_unadjusted(db):
    from app.services.derivations import derive_valuation_signal_inputs

    company = _priced_company(db, "NOBM", 900e6, _ramp(50, 100))
    derived = derive_valuation_signal_inputs(db.session, company, benchmark_symbol="XLV")
    assert derived["valuation_basis"] == BASIS_OWN_RANGE
    assert "no benchmark to adjust against" in derived["valuation_basis_detail"]
