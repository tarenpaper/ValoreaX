"""Historical buy-and-hold accounting; no current financials or analyst views are used."""
from datetime import date
from math import isfinite
from statistics import mean

from app.providers.base import PricePoint


def trend_at(points: list[PricePoint], as_of: date) -> dict:
    history = [point for point in sorted(points, key=lambda p: p.date) if point.date <= as_of]
    recent = history[-60:]
    result = {"as_of": history[-1].date.isoformat() if history else None,
              "label": "insufficient_history", "sma20": None, "sma60": None,
              "trailing_return": None}
    if len(recent) < 60:
        return result
    short, long = mean(p.close for p in recent[-20:]), mean(p.close for p in recent)
    price = recent[-1].close
    label = "positive" if price > short > long else "negative" if price < short < long else "mixed"
    return {"as_of": recent[-1].date.isoformat(), "label": label,
            "sma20": round(short, 4), "sma60": round(long, 4),
            "trailing_return": price / recent[0].close - 1}


def simulate(prices: list[PricePoint], benchmark: list[PricePoint], start: date,
             end: date, investment: float) -> dict:
    if not isfinite(investment) or investment <= 0:
        raise ValueError("Investment must be a positive finite dollar amount.")
    for point in [*prices, *benchmark]:
        if not isfinite(point.close) or point.close <= 0:
            raise ValueError("Price history contains invalid closing prices.")
    stock = {p.date: p.close for p in prices if start <= p.date <= end}
    index = {p.date: p.close for p in benchmark if start <= p.date <= end}
    days = sorted(stock.keys() & index.keys())
    if len(days) < 2:
        raise ValueError("Choose a period with at least two trading sessions shared by the stock and benchmark.")
    first, last = days[0], days[-1]
    if (first - start).days > 7 or (end - last).days > 7:
        raise ValueError(f"History does not cover the requested period. Shared prices run from {first} to {last}; choose dates within that range.")
    if any((right - left).days > 7 for left, right in zip(days, days[1:], strict=False)):
        raise ValueError("Historical prices contain a gap longer than seven days. Choose another period or retry the provider.")
    units, benchmark_units = investment / stock[first], investment / index[first]
    ordered = sorted(prices, key=lambda point: point.date)
    price_dates = {point.date: i for i, point in enumerate(ordered)}
    peak = investment
    curve = []
    for day in days:
        value, comparison = units * stock[day], benchmark_units * index[day]
        peak = max(peak, value)
        position = price_dates[day]
        outlook = trend_at(ordered[max(0, position - 59):position + 1], day)
        curve.append({"date": day.isoformat(), "close": stock[day],
                      "value": round(value, 2), "benchmark_value": round(comparison, 2),
                      "return_pct": stock[day] / stock[first] - 1,
                      "outlook": outlook["label"],
                      "drawdown": value / peak - 1})
    final = units * stock[last]
    total_return = final / investment - 1
    benchmark_return = index[last] / index[first] - 1
    elapsed = (last - first).days
    warnings = []
    if first != start or last != end:
        warnings.append(f"Non-trading dates adjusted to the common closing sessions {first} through {last}.")
    missing = len(stock.keys() ^ index.keys())
    if missing:
        warnings.append(f"Omitted {missing} date(s) without both stock and benchmark prices; no prices were interpolated.")
    before_entry = [p for p in prices if p.date < first]
    entry_trend = trend_at(before_entry, first)
    if entry_trend["label"] == "insufficient_history":
        warnings.append("Not enough pre-investment history for the 60-session trend assessment.")
    return {
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "entry_date": first.isoformat(), "exit_date": last.isoformat(),
        "investment": investment, "final_value": round(final, 2), "profit_loss": round(final - investment, 2),
        "total_return": total_return, "benchmark_return": benchmark_return,
        "benchmark_final_value": round(investment * (1 + benchmark_return), 2),
        "excess_return": total_return - benchmark_return,
        "annualized_return": (1 + total_return) ** (365.25 / elapsed) - 1 if elapsed >= 365 else None,
        "max_drawdown": min(row["drawdown"] for row in curve),
        "trading_sessions": len(days), "entry_close": stock[first], "exit_close": stock[last],
        "curve": curve, "entry_outlook": entry_trend, "exit_outlook": trend_at(prices, last),
        "warnings": warnings,
        "methodology": "Buy at the first common daily close on or after the start date; hold fractional split-adjusted units through the last common close on or before the end date. No intermediate trades. Dividends, fees, taxes, slippage, and interest are excluded. Benchmark uses the same amount and dates.",
        "outlook_methodology": "Historical price trend only: positive when close > 20-session average > 60-session average; negative for the reverse; otherwise mixed. Entry uses only closes before the investment session. Exit uses closes through the exit session. These labels are descriptive, not forecasts or historical analyst opinions.",
    }


def simulate_comparison(prices, benchmarks, start, end, investment):
    """Compare identical investments on sessions shared by every requested asset."""
    histories = [prices, *benchmarks.values()]
    if not benchmarks:
        raise ValueError("At least one benchmark is required.")
    for history in histories:
        if any(not isfinite(p.close) or p.close <= 0 for p in history):
            raise ValueError("Price history contains invalid closing prices.")
    date_sets = [{p.date for p in history if start <= p.date <= end} for history in histories]
    common = set.intersection(*date_sets)
    def aligned(history):
        return [p for p in history if p.date < start or p.date in common]
    stock = aligned(prices)
    primary = next(iter(benchmarks))
    result = simulate(stock, aligned(benchmarks[primary]), start, end, investment)
    # Trend evidence uses all known stock closes, even if a benchmark has a missing date.
    first, last = date.fromisoformat(result['entry_date']), date.fromisoformat(result['exit_date'])
    result['entry_outlook'] = trend_at([p for p in prices if p.date < first], first)
    result['exit_outlook'] = trend_at(prices, last)
    result['benchmarks'] = []
    ordered = sorted(prices, key=lambda p: p.date)
    positions = {p.date: i for i, p in enumerate(ordered)}
    for row in result['curve']:
        row['comparisons'] = {}
        day = date.fromisoformat(row['date'])
        position = positions[day]
        row['outlook'] = trend_at(ordered[max(0, position - 59):position + 1], day)['label']
    for symbol, history in benchmarks.items():
        comparison = simulate(aligned(history), stock, start, end, investment)
        result['benchmarks'].append({
            'symbol': symbol, **{key: comparison[key] for key in (
                'final_value', 'profit_loss', 'total_return', 'annualized_return', 'max_drawdown')},
            'excess_return': result['total_return'] - comparison['total_return'],
        })
        for row, other in zip(result['curve'], comparison['curve'], strict=True):
            row['comparisons'][symbol] = {key: other[key] for key in ('value', 'return_pct', 'drawdown')}
    omitted = len(set.union(*date_sets) - common)
    if omitted:
        result['warnings'].append(f'Omitted {omitted} date(s) without prices for all compared assets; no interpolation.')
    result['methodology'] += ' All comparisons use sessions shared by the stock, SPY and XLV. Returns exclude dividends and are not total returns.'
    return result
