from datetime import date, timedelta

import pytest

from app.providers.base import PricePoint
from app.providers.twelve_data import TwelveDataMarketProvider
from app.services.investment_backtest import simulate, trend_at


def points(values, start=date(2020, 1, 6)):
    return [PricePoint(date=start + timedelta(days=i), close=value) for i, value in enumerate(values)]


def test_dollar_accounting_benchmark_and_drawdown():
    data = simulate(points([100, 120, 90, 110]), points([100, 102, 101, 105]),
                    date(2020, 1, 6), date(2020, 1, 9), 1000)
    assert data["final_value"] == 1100
    assert data["profit_loss"] == 100
    assert data["total_return"] == pytest.approx(.1)
    assert data["benchmark_final_value"] == 1050
    assert data["excess_return"] == pytest.approx(.05)
    assert data["max_drawdown"] == pytest.approx(-.25)
    assert data["curve"][0]["value"] == 1000
    assert data["annualized_return"] is None


def test_fractional_units_weekend_dates_and_amount_scaling():
    prices = points([30, 33, 36])
    a = simulate(prices, prices, date(2020, 1, 4), date(2020, 1, 8), 100)
    b = simulate(prices, prices, date(2020, 1, 4), date(2020, 1, 8), 1000)
    assert a["entry_date"] == "2020-01-06"
    assert a["warnings"]
    assert a["final_value"] == 120
    assert b["final_value"] == 1200
    assert a["total_return"] == b["total_return"]


def test_trend_never_reads_future_prices_and_entry_excludes_investment_day():
    history = points(list(range(100, 180)))
    cutoff = history[59].date
    expected = trend_at(history, cutoff)
    poisoned = history[:60] + points([1] * 20, cutoff + timedelta(days=1))
    assert trend_at(poisoned, cutoff) == expected
    data = simulate(poisoned, history, cutoff + timedelta(days=1), cutoff + timedelta(days=5), 1000)
    assert data["entry_outlook"] == expected
    assert data["entry_outlook"]["label"] == "positive"
    assert data["entry_outlook"]["as_of"] == cutoff.isoformat()
    assert trend_at(history[:20], cutoff)["label"] == "insufficient_history"


def test_annualization_and_no_prices_outside_requested_period():
    prices = points([100] * 366 + [110, 10000])
    data = simulate(prices, prices, prices[0].date, prices[366].date, 1000)
    assert data["annualized_return"] == pytest.approx(1.1 ** (365.25 / 366) - 1)
    assert len(data["curve"]) == 367
    assert data["final_value"] == 1100


def test_incomplete_history_not_silently_simulated():
    prices = points([100, 110])
    with pytest.raises(ValueError, match="does not cover"):
        simulate(prices, prices, date(2019, 1, 1), date(2020, 1, 7), 100)
    with pytest.raises(ValueError, match="two trading"):
        simulate(prices, prices, date(2020, 1, 6), date(2020, 1, 6), 100)
    with pytest.raises(ValueError, match="gap"):
        gap = [PricePoint(date(2020, 1, 1), 100), PricePoint(date(2020, 2, 1), 110)]
        simulate(gap, gap, gap[0].date, gap[-1].date, 100)
    with pytest.raises(ValueError, match="finite"):
        simulate(prices, prices, date(2020, 1, 6), date(2020, 1, 7), float("nan"))


def test_historical_adapter_date_bounds_adjustment_and_filter(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"meta": {"currency": "USD"}, "values": [
                {"datetime": "2020-01-09", "close": "999"},
                {"datetime": "2020-01-08", "close": "110"},
                {"datetime": "2020-01-06", "close": "100"},
            ]}

    def get(url, **kwargs):
        captured.update(kwargs["params"])
        return Response()

    monkeypatch.setattr("app.providers.twelve_data.requests.get", get)
    rows = TwelveDataMarketProvider("test-key").get_history("PFE", date(2020, 1, 6), date(2020, 1, 8))
    assert captured["start_date"] == "2020-01-06"
    assert captured["end_date"] == "2020-01-09"
    assert captured["adjust"] == "splits"
    assert [p.close for p in rows] == [100, 110]


def test_endpoint_auth_cache_and_invalid_inputs(app, client, monkeypatch, token_for):
    client.post("/api/v1/companies", json={"ticker": "VALX"})
    calls = []

    class Provider:
        name = "twelve_data_daily"

        def get_history(self, symbol, start, end):
            calls.append((symbol, start, end))
            return points([100, 110, 120])

    app.config["MARKET_DATA_PROVIDER"] = "twelve_data"
    monkeypatch.setattr("app.api.v1.backtest.get_market_provider", lambda: Provider())
    url = "/api/v1/companies/VALX/backtest"
    payload = {"start_date": "2020-01-06", "end_date": "2020-01-08", "investment": 1000}
    first = client.post(url, json=payload)
    assert first.status_code == 200, first.get_json()
    assert first.get_json()["final_value"] == 1200
    assert first.headers["Cache-Control"] == "private, no-store"
    assert len(calls) == 2
    second = client.post(url, json={**payload, "investment": 2000})
    assert second.get_json()["final_value"] == 2400
    assert len(calls) == 2
    assert all(r["cached"] for r in second.get_json()["retrieval"])
    for invalid in [{"investment": 0}, {"investment": "NaN"}, {"investment": "Infinity"},
                    {"start_date": "2021-01-01"}, {"start_date": "1900-01-01"},
                    {"end_date": "2999-01-01"}, {"start_date": "bad"}]:
        assert client.post(url, json={**payload, **invalid}).status_code == 422
    other = app.test_client()
    assert other.post(url, json=payload).status_code == 401
    other.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token_for('22222222-2222-4222-8222-222222222222')}"
    assert other.post(url, json=payload).status_code == 404
