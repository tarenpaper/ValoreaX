"""Live Financial Modeling Prep (FMP) analyst adapter.

Assembles analyst coverage from several FMP endpoints (each fetched tolerantly so
one premium/empty endpoint doesn't sink the whole pull):

  * /api/v3/analyst-stock-recommendations/{symbol} → rating distribution (latest row)
  * /api/v4/price-target-consensus?symbol=…        → target high/low/consensus/median
  * /api/v3/quote/{symbol}                          → current price (for implied upside)
  * /api/v3/grade/{symbol}                          → recent per-institution grades

All parsing lives in pure `_map_*` / `consensus_label` helpers so it can be unit
tested against captured fixtures with no network. Nothing is fabricated: whatever
an endpoint doesn't return is left null with a warning.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import requests

from .base import (
    AnalystConsensusData,
    AnalystData,
    AnalystDataProvider,
    AnalystRatingRecord,
    ProviderError,
)

_BULLISH = {"buy", "outperform", "overweight", "strong buy", "accumulate", "positive", "add"}
_BEARISH = {"sell", "underperform", "underweight", "strong sell", "reduce", "negative"}
_PARALLEL_ENDPOINTS = (
    "/stable/grades-consensus",
    "/stable/price-target-consensus",
    "/stable/quote",
    "/stable/grades",
)


def consensus_label(sb: int, b: int, h: int, s: int, ss: int) -> str | None:
    """Map a rating distribution to a single consensus label."""
    total = sb + b + h + s + ss
    if not total:
        return None
    score = (sb * 2 + b - s - ss * 2) / total
    if score >= 1.0:
        return "Strong Buy"
    if score >= 0.25:
        return "Buy"
    if score > -0.25:
        return "Hold"
    if score > -1.0:
        return "Sell"
    return "Strong Sell"


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value):
    try:
        f = float(value)
        return f if f else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value)[:26], fmt).date()
        except (ValueError, TypeError):
            continue
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _first(row: dict, *keys):
    for key in keys:
        if key in row:
            return row.get(key)
    return None


def _map_grades_consensus(row: dict) -> dict:
    """Rating-bucket counts from FMP's /stable/grades-consensus row."""
    return {
        "strong_buy": _to_int(row.get("strongBuy")),
        "buy": _to_int(row.get("buy")),
        "hold": _to_int(row.get("hold")),
        "sell": _to_int(row.get("sell")),
        "strong_sell": _to_int(row.get("strongSell")),
    }


def _map_recommendation_row(row: dict) -> dict:
    """Rating-bucket counts from a grades-historical row (tolerant to key casing)."""
    return {
        "strong_buy": _to_int(_first(row, "analystRatingsStrongBuy")),
        "buy": _to_int(_first(row, "analystRatingsBuy", "analystRatingsbuy")),
        "hold": _to_int(_first(row, "analystRatingsHold")),
        "sell": _to_int(_first(row, "analystRatingsSell")),
        "strong_sell": _to_int(_first(row, "analystRatingsStrongSell")),
    }


def _grade_action(previous: str | None, new: str | None) -> str:
    """Classify a grade change into upgrade / downgrade / initiate / maintain."""
    def rank(grade: str | None) -> int | None:
        if not grade:
            return None
        g = grade.strip().lower()
        if g in _BULLISH:
            return 1
        if g in _BEARISH:
            return -1
        return 0
    new_rank = rank(new)
    prev_rank = rank(previous)
    if not previous:
        return "initiate"
    if new_rank is None or prev_rank is None or new_rank == prev_rank:
        return "maintain"
    return "upgrade" if new_rank > prev_rank else "downgrade"


def _map_grade_row(row: dict) -> AnalystRatingRecord | None:
    institution = row.get("gradingCompany") or row.get("analystCompany")
    if not institution:
        return None
    # FMP's /stable/grades gives an explicit `action`; fall back to inferring it.
    action = row.get("action") or _grade_action(row.get("previousGrade"), row.get("newGrade"))
    dated = row.get("date") or row.get("publishedDate")
    return AnalystRatingRecord(
        institution=str(institution)[:128],
        grade=row.get("newGrade"),
        action=action,
        price_target=_to_float(row.get("priceTarget")),
        rating_date=_parse_date(dated),
        external_id=f"{institution}:{dated}",
    )


class FmpAnalystProvider(AnalystDataProvider):
    name = "fmp"

    def __init__(self, api_key: str, base_url: str = "https://financialmodelingprep.com",
                 timeout: int = 20, max_ratings: int = 10) -> None:
        if not api_key:
            raise ProviderError("FMP_API_KEY is required when ANALYST_PROVIDER=fmp.")
        self._key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_ratings = max_ratings

    def _try_get(self, path: str, params: dict | None = None):
        """GET returning parsed JSON, or None on any failure (tolerant fetch)."""
        params = {**(params or {}), "apikey": self._key}
        try:
            # One request per call so the four independent endpoints can run together.
            resp = requests.get(
                f"{self._base_url}{path}", params=params, timeout=self._timeout,
            )
        except requests.RequestException:  # pragma: no cover - network dependent
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:  # pragma: no cover
            return None
        # FMP signals plan/errors via a dict with "Error Message".
        if isinstance(data, dict) and "Error Message" in data:
            return None
        return data

    def _fetch_parallel(self, symbol: str) -> dict[str, object]:
        params = {"symbol": symbol}
        with ThreadPoolExecutor(max_workers=len(_PARALLEL_ENDPOINTS)) as pool:
            futs = {path: pool.submit(self._try_get, path, params) for path in _PARALLEL_ENDPOINTS}
            return {path: fut.result() for path, fut in futs.items()}

    def fetch(self, ticker: str) -> AnalystData:
        symbol = ticker.upper()
        warnings: list[str] = []
        consensus = AnalystConsensusData(as_of_date=date.today())
        payloads = self._fetch_parallel(symbol)

        # Rating distribution + label: grades-consensus, falling back to grades-historical.
        gc = payloads["/stable/grades-consensus"]
        if isinstance(gc, list):
            gc = gc[0] if gc else None
        if isinstance(gc, dict) and any(_map_grades_consensus(gc).values()):
            counts = _map_grades_consensus(gc)
            for key, value in counts.items():
                setattr(consensus, key, value)
            consensus.analyst_count = sum(counts.values())
            consensus.consensus_label = gc.get("consensus") or consensus_label(
                counts["strong_buy"], counts["buy"], counts["hold"],
                counts["sell"], counts["strong_sell"])
        else:
            hist = self._try_get("/stable/grades-historical", {"symbol": symbol})
            if isinstance(hist, list) and hist:
                counts = _map_recommendation_row(hist[0])
                for key, value in counts.items():
                    setattr(consensus, key, value)
                consensus.analyst_count = sum(counts.values())
                consensus.consensus_label = consensus_label(
                    counts["strong_buy"], counts["buy"], counts["hold"],
                    counts["sell"], counts["strong_sell"])
                consensus.as_of_date = _parse_date(hist[0].get("date")) or consensus.as_of_date
            else:
                warnings.append("No analyst rating distribution returned by FMP.")

        target = payloads["/stable/price-target-consensus"]
        if isinstance(target, list):
            target = target[0] if target else None
        if isinstance(target, dict):
            consensus.target_high = _to_float(target.get("targetHigh"))
            consensus.target_low = _to_float(target.get("targetLow"))
            consensus.target_consensus = _to_float(target.get("targetConsensus"))
            consensus.target_median = _to_float(target.get("targetMedian"))
        else:
            warnings.append("No price-target consensus returned by FMP.")

        quote = payloads["/stable/quote"]
        if isinstance(quote, list) and quote:
            consensus.current_price = _to_float(quote[0].get("price"))
        if consensus.current_price is None:
            warnings.append("No current price returned by FMP (implied upside unavailable).")

        ratings: list[AnalystRatingRecord] = []
        grades = payloads["/stable/grades"]
        if isinstance(grades, list):
            for row in grades[: self._max_ratings]:
                record = _map_grade_row(row)
                if record is not None:
                    ratings.append(record)

        return AnalystData(consensus=consensus, ratings=ratings, warnings=warnings)
