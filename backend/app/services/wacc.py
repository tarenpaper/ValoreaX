"""Company WACC with explicit market inputs, accounting proxies and fallback assumptions."""
from __future__ import annotations

import csv
import io
import math
from datetime import date, timedelta

import requests
from flask import current_app
from sqlalchemy import select

from app.models import BenchmarkPrice, MarketPrice
from app.providers import get_market_provider, ProviderError
from app.services.cache_service import CacheService


def finite(value):
    return value is not None and math.isfinite(value)


def historical_beta(stock, market):
    """OLS beta from returns over identical date intervals, using at most 252 returns."""
    common = sorted(set(stock) & set(market))[-253:]
    pairs = [(stock[b] / stock[a] - 1, market[b] / market[a] - 1)
             for a, b in zip(common, common[1:])
             if 0 < (b - a).days <= 7 and all(finite(v) and v > 0 for v in
                 (stock[a], stock[b], market[a], market[b]))]
    if len(pairs) < 60:
        return None, len(pairs)
    sy = sum(y for y, _ in pairs) / len(pairs)
    sx = sum(x for _, x in pairs) / len(pairs)
    variance = sum((x - sx) ** 2 for _, x in pairs)
    return (sum((x - sx) * (y - sy) for y, x in pairs) / variance
            if variance > 1e-12 else None), len(pairs)


def calculate_wacc(metrics, price, beta, risk_free_rate, equity_risk_premium=0.05,
                   debt_spread=0.03):
    """Book debt proxies market debt; historical borrowing cost is not a bond yield."""
    warnings = []
    def number(key):
        value = metrics.get(key)
        return value if finite(value) else None
    shares, debt = number('shares_outstanding'), number('total_debt')
    equity = price * shares if finite(price) and price > 0 and shares and shares > 0 else None
    beta_source = 'SPY price-return regression'
    if not finite(beta):
        beta, beta_source = 1.0, 'Assumed market beta (insufficient usable history)'
        warnings.append('Beta defaults to 1.0: at least 60 aligned returns are required.')
    cost_equity = risk_free_rate + beta * equity_risk_premium
    interest = number('interest_expense')
    cost_debt = risk_free_rate + debt_spread
    debt_source = 'Assumed risk-free rate plus credit spread'
    if debt is not None and debt > 0 and interest is not None and interest >= 0:
        cost_debt = max(risk_free_rate, interest / debt)
        debt_source = 'Annual interest / year-end book debt, floored at risk-free rate'
    elif debt and debt > 0:
        warnings.append('Interest expense unavailable; borrowing cost uses an assumed credit spread.')
    # Loss-making companies may not be able to use interest tax deductions currently.
    pretax = number('pretax_income')
    tax_rate = 0.21 if pretax is not None and pretax > 0 else 0.0
    warnings.append('Tax shield uses an assumed 21% US federal rate only with positive pretax income; otherwise 0%.')
    warnings.append('Book debt approximates market debt; equity uses reported shares times the latest price.')
    raw = None
    ew = dw = None
    if equity is not None and debt is not None and debt >= 0:
        ew, dw = equity / (equity + debt), debt / (equity + debt)
        raw = ew * cost_equity + dw * cost_debt * (1 - tax_rate)
    usable = finite(raw) and 0.01 <= raw <= 0.50
    if not usable:
        warnings.append('A supported WACC could not be calculated (missing capital inputs or rate outside 1–50%); using the 10% fallback.')
    return dict(rate=raw if usable else 0.10, calculated_rate=raw, status='estimated' if usable else 'fallback',
                beta=beta, beta_source=beta_source, risk_free_rate=risk_free_rate,
                equity_risk_premium=equity_risk_premium, cost_of_equity=cost_equity,
                cost_of_debt=cost_debt, debt_source=debt_source, debt_spread=debt_spread,
                tax_rate=tax_rate, market_equity=equity, book_debt=debt,
                equity_weight=ew, debt_weight=dw, warnings=warnings)


def company_wacc(session, company, metrics, quote):
    cache = CacheService(session)
    today = date.today()
    live = current_app.config.get('ENV') != 'testing' and current_app.config.get('MARKET_DATA_PROVIDER') != 'mock'
    warnings = []
    cutoff = today - timedelta(days=400)
    source = current_app.config.get('MARKET_DATA_PROVIDER')
    stock = {p.date: p.close for p in session.execute(select(MarketPrice).where(
        MarketPrice.company_id == company.id, MarketPrice.date >= cutoff, MarketPrice.date <= today,
        MarketPrice.source == source)).scalars()}
    market = {p.date: p.close for p in session.execute(select(BenchmarkPrice).where(
        BenchmarkPrice.symbol == 'SPY', BenchmarkPrice.date >= cutoff, BenchmarkPrice.date <= today,
        BenchmarkPrice.source == source)).scalars()}
    if live:
        provider = get_market_provider()
        for symbol, target in ((company.ticker, stock), ('SPY', market)):
            key = f'{provider.name}:{symbol}:400'
            payload = cache.get('wacc_prices', key)
            if payload is None:
                try:
                    points = provider.get_prices(symbol, lookback_days=400)
                    payload = {'points': [[p.date.isoformat(), p.close] for p in points]}
                    cache.set('wacc_prices', key, payload, 86400)
                except ProviderError:
                    payload = {'points': [], 'unavailable': True}
                    cache.set('wacc_prices', key, payload, 300)
            # Prefer the more recent stored series for overlapping dates.
            target_copy = {date.fromisoformat(d): v for d, v in payload['points']
                           if cutoff <= date.fromisoformat(d) <= today}
            target_copy.update(target)
            target.clear()
            target.update(target_copy)
            if payload.get('unavailable'):
                warnings.append(f'{symbol} history unavailable; using stored prices where possible.')
    beta, observations = historical_beta(stock, market)
    if not stock or not market or min(max(stock), max(market)) < today - timedelta(days=10):
        beta = None
        warnings.append('Recent aligned market history is unavailable; historical beta is not used.')
    rf = cache.get('wacc_macro', 'DGS10') if live else None
    if rf is None and live:
        try:
            response = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv',
                                    params={'id': 'DGS10', 'cosd': (today - timedelta(days=30)).isoformat()}, timeout=5)
            response.raise_for_status()
            rows = []
            for row in csv.DictReader(io.StringIO(response.text)):
                try:
                    observed = date.fromisoformat(row['observation_date'])
                    rate = float(row['DGS10']) / 100
                    if today - timedelta(days=10) <= observed <= today and finite(rate) and 0 <= rate <= .2:
                        rows.append((observed, rate))
                except (KeyError, ValueError):
                    continue
            observed, rate = max(rows)
            rf = {'rate': rate, 'as_of': observed.isoformat(), 'source': 'FRED DGS10 · US 10-year Treasury'}
            cache.set('wacc_macro', 'DGS10', rf, 86400)
        except (requests.RequestException, ValueError):
            rf = {'rate': .04, 'as_of': None, 'source': 'Assumed 4% (Treasury feed unavailable)'}
            cache.set('wacc_macro', 'DGS10', rf, 300)
    rf = rf or {'rate': .04, 'as_of': None, 'source': 'Assumed 4% (sample/offline mode)'}
    if not rf['as_of']:
        warnings.append(rf['source'])
    values = {key: m.value for key, m in metrics.items() if m.status != 'missing'}
    price_day = max(stock) if stock else None
    price = stock.get(price_day) if price_day else None
    if quote and quote.source == source and (price_day is None or quote.date >= price_day):
        price, price_day = quote.close, quote.date
    if price_day and price_day < today - timedelta(days=10):
        price = None
        warnings.append('Latest equity price is stale; WACC capital weights are unavailable.')
    result = calculate_wacc(values, price, beta, rf['rate'])
    result.update(risk_free_source=rf['source'], risk_free_as_of=rf['as_of'],
                  beta_observations=observations, benchmark='SPY',
                  price_as_of=price_day.isoformat() if price_day else None,
                  fiscal_year=max((m.fiscal_year for m in metrics.values() if m.fiscal_year), default=None))
    result['warnings'].extend(warnings)
    result['warnings'].append('The equity risk premium (5%) is a modeling assumption, not a live market observation.')
    return result
