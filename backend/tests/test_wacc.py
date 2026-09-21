from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.wacc import calculate_wacc, historical_beta, company_wacc


def test_capital_weights_costs_and_tax_shield():
    result = calculate_wacc({'shares_outstanding': 100, 'total_debt': 1000,
                             'interest_expense': 80, 'pretax_income': 500}, 40, 1.2, .04)
    assert result['equity_weight'] == .8
    assert result['cost_of_equity'] == pytest.approx(.10)
    assert result['cost_of_debt'] == .08
    assert result['rate'] == pytest.approx(.8 * .10 + .2 * .08 * .79)
    assert result['status'] == 'estimated'


def test_loss_makers_do_not_get_an_immediate_tax_shield():
    result = calculate_wacc({'shares_outstanding': 100, 'total_debt': 1000,
                             'interest_expense': 80, 'pretax_income': -50}, 40, 1.2, .04)
    assert result['tax_rate'] == 0
    assert result['rate'] == pytest.approx(.096)


def test_zero_debt_is_distinct_from_missing_debt():
    common = {'shares_outstanding': 100}
    debt_free = calculate_wacc({**common, 'total_debt': 0}, 40, 1.2, .04)
    assert debt_free['rate'] == pytest.approx(.10)
    assert debt_free['debt_weight'] == 0
    missing = calculate_wacc(common, 40, 1.2, .04)
    assert missing['status'] == 'fallback'
    assert missing['calculated_rate'] is None


def test_missing_or_extreme_inputs_are_explicit():
    missing = calculate_wacc({'shares_outstanding': 100, 'total_debt': 0}, None, None, .04)
    assert missing['status'] == 'fallback'
    assert missing['rate'] == .10
    assert missing['beta'] == 1
    extreme = calculate_wacc({'shares_outstanding': 100, 'total_debt': 0}, 40, 50, .04)
    assert extreme['status'] == 'fallback'
    assert extreme['calculated_rate'] > .5


def price_history():
    stock, market = {}, {}
    s = m = 100
    for i in range(100):
        day = date.today() - timedelta(days=99-i)
        r = (i % 7 - 3) / 1000
        s *= 1 + 1.5 * r
        m *= 1 + r
        stock[day], market[day] = s, m
    return stock, market


def test_beta_uses_matched_return_intervals_and_requires_variance():
    stock, market = price_history()
    beta, observations = historical_beta(stock, market)
    assert observations == 99
    assert beta == pytest.approx(1.5)
    assert historical_beta(dict(list(stock.items())[:20]), market)[0] is None
    assert historical_beta(stock, {d: 100 for d in market})[0] is None


def test_live_inputs_are_cached_and_have_provenance(app, db, monkeypatch):
    from app.models import Company
    stock, market = price_history()
    calls = []
    class Market:
        name = 'test-live'
        def get_prices(self, ticker, lookback_days):
            calls.append(ticker)
            return [SimpleNamespace(date=d, close=p) for d, p in (market if ticker == 'SPY' else stock).items()]
    monkeypatch.setattr('app.services.wacc.get_market_provider', lambda: Market())
    def treasury(*args, **kwargs):
        calls.append('DGS10')
        return SimpleNamespace(raise_for_status=lambda: None,
                               text=f'observation_date,DGS10\n{date.today()},4.2\n')
    monkeypatch.setattr('app.services.wacc.requests.get', treasury)
    app.config.update(ENV='production', MARKET_DATA_PROVIDER='test-live')
    company = Company(ticker='TEST', name='Test'); db.session.add(company); db.session.commit()
    metrics = {key: SimpleNamespace(value=value, status='reported', fiscal_year=2025)
               for key, value in {'shares_outstanding': 100, 'total_debt': 0}.items()}
    first = company_wacc(db.session, company, metrics, None)
    second = company_wacc(db.session, company, metrics, None)
    assert first == second
    assert first['beta'] == pytest.approx(1.5)
    assert first['risk_free_rate'] == .042
    assert first['risk_free_as_of'] == date.today().isoformat()
    assert calls == ['TEST', 'SPY', 'DGS10']


def test_valuation_automatic_manual_and_sensitivity_use_same_rate(client, monkeypatch):
    monkeypatch.setattr('app.services.wacc.company_wacc', lambda *args:
                        {'rate': .087, 'status': 'estimated'})
    assert client.post('/api/v1/companies', json={'ticker': 'VALX'}).status_code == 201
    client.post('/api/v1/companies/VALX/drugs/sync')
    path = '/api/v1/companies/VALX/valuation'
    automatic = client.post(path, json={'include_sensitivity': True}).json
    assert automatic['discount_rate'] == .087
    assert automatic['discount_rate_mode'] == 'automatic'
    assert automatic['sensitivity']['value_per_share'][2][2] == round(automatic['value_per_share'], 2)
    manual = client.post(path, json={'discount_rate': .12}).json
    assert manual['discount_rate'] == .12 and manual['discount_rate_mode'] == 'manual'
    assert manual['wacc']['rate'] == .087
    reset = client.post(path, json={'discount_rate': None}).json
    assert reset['discount_rate'] == .087 and reset['discount_rate_mode'] == 'automatic'
    # Same effective rate must not reuse stale automatic/manual metadata.
    same = client.post(path, json={'discount_rate': .087}).json
    assert same['discount_rate_mode'] == 'manual'


def test_provider_failures_use_labeled_fallbacks_and_short_cache(app, db, monkeypatch):
    import requests
    from app.models import Company
    from app.providers import ProviderError
    calls = []
    class Broken:
        name = 'broken'
        def get_prices(self, *args, **kwargs):
            calls.append('prices')
            raise ProviderError('Unavailable')
    monkeypatch.setattr('app.services.wacc.get_market_provider', lambda: Broken())
    def unavailable(*args, **kwargs):
        calls.append('treasury')
        raise requests.Timeout()
    monkeypatch.setattr('app.services.wacc.requests.get', unavailable)
    app.config.update(ENV='production', MARKET_DATA_PROVIDER='broken')
    company = Company(ticker='TEST', name='Test'); db.session.add(company); db.session.commit()
    first = company_wacc(db.session, company, {}, None)
    assert first['status'] == 'fallback'
    assert first['risk_free_as_of'] is None
    assert 'unavailable' in first['risk_free_source']
    company_wacc(db.session, company, {}, None)
    assert calls == ['prices', 'prices', 'treasury']


def test_stale_prices_do_not_produce_current_capital_weights(app, db):
    from app.models import Company, MarketPrice
    company = Company(ticker='OLD', name='Old'); db.session.add(company); db.session.flush()
    quote = MarketPrice(company_id=company.id, date=date.today()-timedelta(days=30), close=100, source='mock')
    db.session.add(quote); db.session.commit()
    metrics = {key: SimpleNamespace(value=value, status='reported', fiscal_year=2025)
               for key, value in {'shares_outstanding': 100, 'total_debt': 0}.items()}
    assert company_wacc(db.session, company, metrics, quote)['status'] == 'fallback'


def test_existing_filings_upgrade_interest_expense_from_cached_payload(client, app, db, monkeypatch):
    import copy
    from sqlalchemy import delete, select
    from app.models import FinancialMetric
    from app.providers import get_sec_provider
    from app.services.cache_service import CacheService
    provider = get_sec_provider()
    payload = copy.deepcopy(provider.get_company_facts('VALX').payload)
    payload['facts']['us-gaap']['InterestExpense'] = {'units': {'USD': [{
        'val': 8000000, 'start': '2025-01-01', 'end': '2025-12-31', 'fy': 2025,
        'fp': 'FY', 'form': '10-K', 'accn': 'test-interest', 'filed': '2026-02-01'}]}}
    monkeypatch.setattr(provider, 'get_company_facts', lambda ticker: SimpleNamespace(payload=payload))
    response = client.post('/api/v1/companies', json={'ticker': 'VALX'})
    assert response.status_code == 201
    assert db.session.execute(select(FinancialMetric.value).where(
        FinancialMetric.concept == 'interest_expense')).scalar_one() == 8000000
    # Model an account normalized before the interest field was introduced.
    db.session.execute(delete(FinancialMetric).where(FinancialMetric.concept == 'interest_expense'))
    CacheService(db.session).invalidate('normalization_version')
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    assert db.session.execute(select(FinancialMetric.value).where(
        FinancialMetric.concept == 'interest_expense')).scalar_one() == 8000000
