"""Authenticated historical investment simulation, independent of signal evaluation."""
import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, g, jsonify
from marshmallow import Schema, ValidationError, fields, validate, validates_schema

from app.api.errors import ApiError
from app.api.v1.helpers import cache_service, get_company_or_404, get_json_body
from app.models.common import utcnow
from app.providers import get_market_provider
from app.providers.base import PricePoint, ProviderError
from app.providers.factory import get_news_provider
from app.providers.gemini import generate_backtest_explanation
from app.services.investment_backtest import simulate_comparison
from app.services.llm_backtest import (
    backtest_evidence,
    inflection_points,
    news_evidence_ids,
    news_windows,
)

bp = Blueprint("investment_backtest", __name__)


class BacktestSchema(Schema):
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    investment = fields.Float(required=True, validate=validate.Range(min=1, max=1_000_000_000))
    explain = fields.Boolean(load_default=False)
    question = fields.String(load_default="", validate=validate.Length(max=1000))

    @validates_schema
    def dates(self, data, **kwargs):
        start, end = data["start_date"], data["end_date"]
        today = datetime.now(ZoneInfo("America/New_York")).date()
        if start >= end:
            raise ValidationError("Start date must be before end date.")
        if end >= today:
            raise ValidationError("End date must be before today to use completed daily sessions.")
        if start < date(1900, 1, 1) or (end - start).days > 365 * 15:
            raise ValidationError("Choose a period of at most 15 years, starting in 1900 or later.")


@bp.post("/companies/<identifier>/backtest")
def investment_backtest(identifier):
    company = get_company_or_404(identifier)
    args = BacktestSchema().load(get_json_body())
    if current_app.config["MARKET_DATA_PROVIDER"] != "twelve_data":
        raise ApiError("Configure Twelve Data to run a simulation with real historical prices.", status=422)
    provider = get_market_provider()
    start, end = args["start_date"], args["end_date"]
    warmup = start - timedelta(days=120)
    benchmark = "SPY"
    cache = cache_service()
    cached_flags = []

    def history(symbol):
        key = f"{provider.name}:{symbol}:{warmup}:{end}:splits:v1"

        def loader():
            rows = provider.get_history(symbol, warmup, end)
            return {"prices": [{"date": row.date.isoformat(), "close": row.close} for row in rows],
                    "fetched_at": datetime.now(ZoneInfo("UTC")).isoformat()}

        payload, cached = cache.get_or_set("backtest_history", key, 300, loader, provider=provider.name)
        cached_flags.append({"symbol": symbol, "cached": cached, "fetched_at": payload["fetched_at"]})
        return [PricePoint(date=date.fromisoformat(row["date"]), close=row["close"]) for row in payload["prices"]]

    stock_prices = history(company.ticker)
    comparisons = {symbol: stock_prices if company.ticker == symbol else history(symbol)
                   for symbol in ("SPY", "XLV")}
    try:
        result = simulate_comparison(stock_prices, comparisons, start, end, args["investment"])
    except ValueError as exc:
        raise ApiError(str(exc), status=422) from exc

    payload = {"ticker": company.ticker, "benchmark": benchmark,
               "source": provider.name, "adjustment": "splits", "currency": "USD",
               "retrieval": cached_flags, **result}
    if args["explain"]:
        payload["explanation"] = _explain(company, result, benchmark, args["question"], cache)
    return jsonify(payload)


def _news_for(ticker, result, cache):
    """Headlines bracketing each detected inflection, or None when unavailable.

    News is an enhancement to the explanation, never a precondition: a provider that
    lacks history, errors, or is misconfigured simply yields no citable records.
    """
    pivots = inflection_points(result.get("curve") or [])
    if not pivots:
        return None
    try:
        provider = get_news_provider()
    except (ValueError, ProviderError):
        return None
    if not getattr(provider, "supports_history", False):
        return None
    return news_windows(provider, cache, ticker, pivots,
                        ttl=current_app.config.get("CACHE_TTL_NEWS", 3600) * 24)


def _explain(company, result, benchmark, question, cache):
    """Retrospective Plutus commentary on a finished simulation.

    Never raises: the simulation's numbers are the deliverable, so a Gemini outage or
    a missing key degrades to a status the panel renders instead of losing the result.
    """
    if not current_app.config.get("GEMINI_API_KEY"):
        return {"status": "needs_setup",
                "message": "Gemini explanation is ready to connect."}
    evidence = backtest_evidence(result, company.ticker, benchmark,
                                 news=_news_for(company.ticker, result, cache))
    model = current_app.config["GEMINI_MODEL"]
    digest = hashlib.sha256(json.dumps({"evidence": evidence, "question": question},
                                       sort_keys=True).encode()).hexdigest()
    # Bump the version whenever BACKTEST_PROMPT or its schema changes.
    key = f"{g.user_id}:{company.id}:{model}:backtest:v4:{digest}"
    try:
        window = (result["entry_date"], result["exit_date"])

        news_ids = news_evidence_ids(evidence)

        def loader():
            return {"status": "ready", "model": model, "generated_at": utcnow().isoformat(),
                    "evidence": evidence,
                    **generate_backtest_explanation(current_app.config, evidence, question,
                                                    window, news_ids)}

        explanation, cached = cache.get_or_set("gemini_backtest", key, 300, loader,
                                               provider="gemini")
        return {**explanation, "cached": cached}
    except ProviderError as exc:
        return {"status": "error", "message": str(exc)}
