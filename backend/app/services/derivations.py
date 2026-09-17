"""Bridge stored data → engine inputs.

These helpers assemble signal-engine inputs from normalized metrics, catalysts, price
history, the per-drug valuation and stored news. Market-return helpers use only price observations
available on or before the requested endpoint and never label a raw return as an
abnormal return without subtracting the configured benchmark.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from app.models import (
    AnalystConsensus,
    BenchmarkPrice,
    CatalystEvent,
    Company,
    FinancialMetric,
    MarketPrice,
    NewsArticle,
)
from app.services.biotech_profile import build_profile, runway_quarters


def latest_annual_metrics(session, company_id: int) -> dict[str, FinancialMetric]:
    """Return {concept: metric} for the most recent fiscal year on file."""
    latest_fy = session.execute(
        select(func.max(FinancialMetric.fiscal_year)).where(FinancialMetric.company_id == company_id)
    ).scalar()
    stmt = select(FinancialMetric).where(FinancialMetric.company_id == company_id)
    stmt = (stmt.where(FinancialMetric.fiscal_year == latest_fy) if latest_fy is not None
            else stmt.where(FinancialMetric.fiscal_year.is_(None)))
    return {m.concept: m for m in session.execute(stmt).scalars()}


def annual_metrics_by_year(session, company_id: int, latest_n: int | None = None
                           ) -> dict[int, dict[str, FinancialMetric]]:
    """Return {fiscal_year: {concept: metric}} for fiscal years on file.

    ``latest_n`` limits the load to the most recent N years (dashboard stage
    classification only needs this year and last year).
    """
    stmt = select(FinancialMetric).where(FinancialMetric.company_id == company_id)
    if latest_n is not None:
        years = list(session.execute(
            select(FinancialMetric.fiscal_year)
            .where(FinancialMetric.company_id == company_id,
                   FinancialMetric.fiscal_year.is_not(None))
            .distinct()
            .order_by(FinancialMetric.fiscal_year.desc())
            .limit(latest_n)
        ).scalars())
        if not years:
            return {}
        stmt = stmt.where(FinancialMetric.fiscal_year.in_(years))
    by_year: dict[int, dict[str, FinancialMetric]] = {}
    for metric in session.execute(stmt).scalars():
        if metric.fiscal_year is not None:
            by_year.setdefault(metric.fiscal_year, {})[metric.concept] = metric
    return by_year


def biotech_profile(session, company_id: int) -> dict | None:
    """Stage classification and biotech figures for the latest fiscal year, or None."""
    by_year = annual_metrics_by_year(session, company_id, latest_n=2)
    if not by_year:
        return None
    latest = max(by_year)
    return build_profile(by_year[latest], by_year.get(latest - 1), fiscal_year=latest)


def estimate_cash_runway_quarters(session, company_id: int) -> float | None:
    """Quarters of funding: liquidity ÷ quarterly operating cash burn.

    Shares its definition with the dashboard (`biotech_profile.runway_quarters`).
    Liquidity includes marketable securities and burn comes from operating cash flow;
    both fall back to cash and operating loss for metrics stored before those concepts
    were normalized. Returns None when the company is not burning cash.
    """
    return runway_quarters(latest_annual_metrics(session, company_id))


def _aligned_closes(session, company_id: int, benchmark_symbol: str) -> list[tuple[date, float, float]]:
    """Return dates where both the issuer and benchmark have a valid close."""
    company_rows = session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company_id)
    ).scalars().all()
    benchmark_rows = session.execute(
        select(BenchmarkPrice).where(BenchmarkPrice.symbol == benchmark_symbol.upper())
    ).scalars().all()
    company_by_date = {row.date: row.close for row in company_rows if row.close > 0}
    benchmark_by_date = {row.date: row.close for row in benchmark_rows if row.close > 0}
    return [
        (observed_on, company_by_date[observed_on], benchmark_by_date[observed_on])
        for observed_on in sorted(set(company_by_date) & set(benchmark_by_date))
    ]


def _return(start: float, end: float) -> float | None:
    if start <= 0:
        return None
    return end / start - 1.0


def event_window_abnormal_return(
    session,
    company_id: int,
    benchmark_symbol: str,
    event_date: date,
    window_trading_days: int = 5,
) -> dict | None:
    """Calculate close-to-close benchmark-adjusted return around a dated event.

    The window begins at the close immediately preceding the first trading session
    on or after ``event_date`` and ends ``window_trading_days`` sessions later.
    This captures the event-day move plus the following sessions. The calculation
    is a simple excess return (issuer return minus benchmark return), not a
    market-model alpha or total-return series.
    """
    if window_trading_days < 1:
        raise ValueError("window_trading_days must be at least 1")
    aligned = _aligned_closes(session, company_id, benchmark_symbol)
    event_index = next((i for i, row in enumerate(aligned) if row[0] >= event_date), None)
    if event_index is None or event_index == 0:
        return None
    exit_index = event_index + window_trading_days
    if exit_index >= len(aligned):
        return None

    start_date, start_company, start_benchmark = aligned[event_index - 1]
    end_date, end_company, end_benchmark = aligned[exit_index]
    company_return = _return(start_company, end_company)
    benchmark_return = _return(start_benchmark, end_benchmark)
    if company_return is None or benchmark_return is None:
        return None
    abnormal_return = company_return - benchmark_return
    return {
        "event_date": event_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "window_trading_days": window_trading_days,
        "benchmark": benchmark_symbol.upper(),
        "company_return": round(company_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "abnormal_return": round(abnormal_return, 6),
        "methodology": "close-to-close issuer return minus benchmark return",
    }


def trailing_benchmark_adjusted_return(
    session,
    company_id: int,
    benchmark_symbol: str,
    lookback_trading_days: int = 20,
) -> dict | None:
    """Calculate a recent benchmark-adjusted return when no resolved catalyst exists."""
    if lookback_trading_days < 1:
        raise ValueError("lookback_trading_days must be at least 1")
    aligned = _aligned_closes(session, company_id, benchmark_symbol)
    if len(aligned) <= lookback_trading_days:
        return None
    start_date, start_company, start_benchmark = aligned[-(lookback_trading_days + 1)]
    end_date, end_company, end_benchmark = aligned[-1]
    company_return = _return(start_company, end_company)
    benchmark_return = _return(start_benchmark, end_benchmark)
    if company_return is None or benchmark_return is None:
        return None
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "window_trading_days": lookback_trading_days,
        "benchmark": benchmark_symbol.upper(),
        "company_return": round(company_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "abnormal_return": round(company_return - benchmark_return, 6),
        "methodology": "trailing close-to-close issuer return minus benchmark return",
    }


def latest_catalyst_abnormal_return(
    session,
    company_id: int,
    benchmark_symbol: str,
    as_of: date,
    window_trading_days: int = 5,
) -> dict | None:
    """Return the latest fully observable resolved-catalyst excess return."""
    resolved = session.execute(
        select(CatalystEvent).where(
            CatalystEvent.company_id == company_id,
            CatalystEvent.actual_date.is_not(None),
            CatalystEvent.actual_date <= as_of,
            CatalystEvent.outcome != "pending",
        )
    ).scalars().all()
    resolved.sort(key=lambda catalyst: catalyst.actual_date or date.min, reverse=True)
    for catalyst in resolved:
        result = event_window_abnormal_return(
            session, company_id, benchmark_symbol, catalyst.actual_date, window_trading_days
        )
        if result is not None:
            result["catalyst_id"] = catalyst.id
            result["catalyst_event_type"] = catalyst.event_type
            return result
    return None


def consensus_rating_score(sb: int, b: int, h: int, s: int, ss: int) -> float | None:
    """Normalize a rating distribution to a tilt in [-1, +1] for the signal engine."""
    total = sb + b + h + s + ss
    if not total:
        return None
    return round((sb * 1.0 + b * 0.5 - s * 0.5 - ss * 1.0) / total, 4)


def derive_analyst_signal_inputs(session, company_id: int) -> dict:
    """Return {analyst_consensus, analyst_label, analyst_target_upside} from stored coverage.

    analyst_target_upside is the consensus price target vs. current price, used to
    auto-fill the signal's valuation_upside when the user hasn't supplied one.
    """
    row = session.execute(
        select(AnalystConsensus).where(AnalystConsensus.company_id == company_id)
    ).scalar_one_or_none()
    if row is None:
        return {}
    score = consensus_rating_score(row.strong_buy, row.buy, row.hold, row.sell, row.strong_sell)
    upside = None
    if row.target_consensus and row.current_price and row.current_price > 0:
        upside = round(row.target_consensus / row.current_price - 1.0, 6)
    return {
        "analyst_consensus": score,
        "analyst_label": row.consensus_label,
        "analyst_target_upside": upside,
    }


def next_catalyst_context(session, company_id: int, as_of: date | None = None) -> dict:
    """Return outcome/event_type/days_to_next for the signal engine."""
    as_of = as_of or date.today()
    catalysts = session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all()

    resolved = [c for c in catalysts if c.outcome and c.outcome != "pending"]
    resolved.sort(key=lambda c: c.actual_date or c.expected_date or date.min, reverse=True)
    upcoming = [
        c for c in catalysts
        if c.outcome == "pending" and c.expected_date and c.expected_date >= as_of
    ]
    upcoming.sort(key=lambda c: c.expected_date)

    outcome = resolved[0].outcome if resolved else ("pending" if upcoming else None)
    event_type = resolved[0].event_type if resolved else (upcoming[0].event_type if upcoming else None)
    days_to_next = (upcoming[0].expected_date - as_of).days if upcoming else None
    return {"catalyst_outcome": outcome, "event_type": event_type, "days_to_next_catalyst": days_to_next}


# --- Signal inputs derived from the drug valuation, filings and news ----------------
# `value_company` imports this module, so it is imported inside the functions below to
# avoid a circular import at module load (the same pattern as `llm_research`).

PEER_SET_MIN = 3                  # fewer valued peers than this and the median means nothing
OWN_RANGE_MIN_OBSERVATIONS = 30   # a trailing median needs a real window, not a few closes
NEWS_WINDOW_DAYS = 90
NEWS_IMPACT_TIERS = ("critical", "high")
# A provider's own sentiment score is trusted above our keyword heuristic.
NEWS_METHOD_WEIGHT = {"provider": 1.0, "heuristic": 0.6}
PEER_CACHE_TTL = 300


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def peer_valuation_multiples(session, company, cache=None, own=None) -> dict[str, float]:
    """price ÷ sum-of-the-parts value per share for every valued company this owner holds.

    Includes `company` itself, so the median is the premium the whole set carries. Each
    valuation costs a few milliseconds, so the result is cached briefly per owner.
    Pass ``own`` to reuse a valuation already computed for ``company``.
    """
    from app.services.rnpv_valuation import value_company

    def compute() -> dict[str, float]:
        peers = session.execute(
            select(Company).where(Company.owner_id == company.owner_id)
        ).scalars().all() if company.owner_id else [company]
        multiples: dict[str, float] = {}
        for peer in peers:
            try:
                result = (own if own is not None and peer.id == company.id
                          else value_company(session, peer, include_sensitivity=False))
            except (TypeError, ValueError, KeyError, ZeroDivisionError):
                continue
            if result["price_to_sotp"]:
                multiples[peer.ticker] = round(result["price_to_sotp"], 4)
        return multiples

    if cache is None:
        return compute()
    key = f"{company.owner_id}:{date.today().isoformat()}"
    payload, _ = cache.get_or_set("signal_peer_multiples", key, PEER_CACHE_TTL, compute)
    return payload


def _own_range_reference(session, company_id: int, value_per_share: float,
                         benchmark_symbol: str | None = None) -> tuple[float, str] | None:
    """The company's own trailing multiple median, for when there are too few peers.

    Each historical close is carried forward by the benchmark's move since that day, so
    the reference answers "what would this have been worth had it merely tracked the
    market?". Without that control a sector-wide rally reads as the company becoming
    expensive, which is exactly the move the momentum component reports as *nothing
    company-specific* — one fact scored twice, in opposite directions.

    Peer comparison needs no such correction: a market-wide move lifts the peer median
    too. Only this basis, judging a company against its own past, is exposed.
    """
    aligned = _aligned_closes(session, company_id, benchmark_symbol) if benchmark_symbol else []
    if len(aligned) >= OWN_RANGE_MIN_OBSERVATIONS:
        _, _, benchmark_now = aligned[-1]
        carried = [close * (benchmark_now / benchmark) / value_per_share
                   for _, close, benchmark in aligned if benchmark > 0]
        reference = _median(carried)
        if reference:
            return reference, (f"{len(carried)} daily closes, carried at "
                               f"{benchmark_symbol.upper()}")

    # No aligned benchmark history: fall back to the raw median and say which it is,
    # rather than dropping the largest component in the engine.
    closes = [row.close for row in session.execute(
        select(MarketPrice).where(MarketPrice.company_id == company_id)
    ).scalars().all() if row.close and row.close > 0]
    if len(closes) < OWN_RANGE_MIN_OBSERVATIONS:
        return None
    reference = _median([close / value_per_share for close in closes])
    return (reference, f"{len(closes)} daily closes, no benchmark to adjust against") if reference else None


def derive_valuation_signal_inputs(session, company, cache=None,
                                   benchmark_symbol: str | None = None,
                                   valuation=None) -> dict:
    """The valuation multiple and the reference it should be judged against.

    Sum-of-the-parts value carries no terminal value, so the multiple is above 1× almost
    everywhere; only the deviation from a reference is informative.
    """
    from app.services.rnpv_valuation import value_company

    own = valuation
    if own is None:
        try:
            own = value_company(session, company, include_sensitivity=False)
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            return {}
    multiple, value_per_share = own["price_to_sotp"], own["value_per_share"]
    if not multiple or not value_per_share:
        return {}

    multiples = peer_valuation_multiples(session, company, cache, own=own)
    if len(multiples) >= PEER_SET_MIN:
        reference = _median(list(multiples.values()))
        return {"valuation_multiple": multiple, "valuation_reference": reference,
                "valuation_basis": "peer_median",
                "valuation_basis_detail": f"{len(multiples)} valued companies"}

    own_range = _own_range_reference(session, company.id, value_per_share, benchmark_symbol)
    if own_range is None:
        return {}
    reference, detail = own_range
    return {"valuation_multiple": multiple, "valuation_reference": reference,
            "valuation_basis": "own_range", "valuation_basis_detail": detail}


def derive_structural_signal_inputs(session, company, valuation=None) -> dict:
    """Patent-cliff exposure and value concentration from the per-drug valuation."""
    from app.services.rnpv_valuation import value_company

    result = valuation
    if result is None:
        try:
            result = value_company(session, company, include_sensitivity=False)
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            return {}
    valued = [a for a in result["assets"] if a["rnpv"]]
    total = result["asset_value"]
    if not valued or not total:
        return {}

    start_year = result["start_year"]
    weighted = [(a["rnpv"], max(0.0, a["loe_year"] - start_year)) for a in valued if a["loe_year"]]
    inputs: dict = {}
    if weighted:
        weight_sum = sum(rnpv for rnpv, _ in weighted)
        if weight_sum:
            inputs["exclusivity_years"] = round(
                sum(rnpv * years for rnpv, years in weighted) / weight_sum, 3)

    pipeline = sum(a["rnpv"] for a in valued if a["kind"] == "pipeline")
    inputs["pipeline_value_share"] = round(max(0.0, pipeline) / total, 4)

    top = max(valued, key=lambda a: a["rnpv"])
    inputs["value_concentration"] = round(top["rnpv"] / total, 4)
    inputs["top_asset_name"] = top["name"]
    return inputs


def derive_financial_health_inputs(session, company_id: int) -> dict:
    """Runway, free cash flow margin and dilution, whichever the filings support."""
    profile = biotech_profile(session, company_id)
    if not profile:
        return {}
    figures = profile["figures"]

    def usable(name: str) -> float | None:
        figure = figures.get(name) or {}
        return figure.get("value") if figure.get("status") in ("reported", "derived") else None

    return {key: value for key, value in (
        ("cash_runway_quarters", usable("runway_quarters")),
        ("fcf_margin", usable("fcf_margin")),
        ("dilution_yoy", usable("dilution_yoy")),
    ) if value is not None}


def derive_news_signal_inputs(session, company_id: int, as_of: date | None = None) -> dict:
    """Sentiment from high-impact articles only, weighted by recency and by method.

    Low-impact headlines are excluded rather than averaged in: a run of routine PR would
    otherwise dilute a genuine readout. The classification is a labelled heuristic and the
    component says so.
    """
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=NEWS_WINDOW_DAYS)
    articles = session.execute(
        select(NewsArticle).where(NewsArticle.company_id == company_id)
    ).scalars().all()

    weighted_sum = 0.0
    weight_total = 0.0
    counted = 0
    for article in articles:
        if (article.impact or "").lower() not in NEWS_IMPACT_TIERS:
            continue
        published = article.published_at.date() if article.published_at else None
        if published is None or published < cutoff or published > as_of:
            continue
        age = (as_of - published).days
        recency = 1.0 - (age / NEWS_WINDOW_DAYS) * 0.5      # oldest article counts half
        weight = recency * NEWS_METHOD_WEIGHT.get((article.sentiment_method or "").lower(), 0.6)
        weighted_sum += (article.sentiment_score or 0.0) * weight
        weight_total += weight
        counted += 1

    if not counted or not weight_total:
        return {}
    return {"news_sentiment": round(weighted_sum / weight_total, 4), "news_article_count": counted}
