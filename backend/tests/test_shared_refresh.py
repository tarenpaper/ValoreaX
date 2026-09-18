from datetime import date
from sqlalchemy import select
from app.models import CacheEntry
from app.providers import PricePoint
from app.services.cache_service import CacheService


def test_second_account_receives_refreshed_shared_prices(client, app, db, token_for, monkeypatch):
    other = app.test_client()
    other.environ_base['HTTP_AUTHORIZATION'] = f"Bearer {token_for('22222222-2222-4222-8222-222222222222')}"
    quote = [100]
    class Market:
        name = 'review'
        def get_prices(self, ticker, lookback_days):
            return [PricePoint(date=date.today(), close=quote[0])]
    monkeypatch.setattr('app.api.v1.prices.get_market_provider', lambda: Market())
    for account in (client, other):
        assert account.post('/api/v1/companies', json={'ticker':'VALX'}).status_code == 201
        assert account.post('/api/v1/companies/VALX/prices/sync').status_code == 201
    CacheService(db.session).invalidate('recent_prices')
    quote[0] = 200
    assert client.post('/api/v1/companies/VALX/prices/sync').status_code == 201
    assert other.post('/api/v1/companies/VALX/prices/sync').status_code == 201
    prices = [a.get('/api/v1/watchlist').json['companies'][0]['price'] for a in (client, other)]
    assert prices == [200, 200]


def test_second_account_persists_new_shared_financial_payload(client, app, db, token_for, monkeypatch):
    import copy
    from types import SimpleNamespace
    from app.models import Company, FinancialMetric
    from app.providers import get_sec_provider
    other = app.test_client()
    other.environ_base['HTTP_AUTHORIZATION'] = f"Bearer {token_for('22222222-2222-4222-8222-222222222222')}"
    for account in (client, other):
        assert account.post('/api/v1/companies', json={'ticker':'VALX'}).status_code == 201
    provider = get_sec_provider()
    payload = copy.deepcopy(provider.get_company_facts('VALX').payload)
    for taxonomy in payload['facts'].values():
        for fact in taxonomy.values():
            for unit, entries in fact.get('units', {}).items():
                if unit == 'USD':
                    for entry in entries:
                        entry['val'] *= 2
    monkeypatch.setattr(provider, 'get_company_facts', lambda ticker: SimpleNamespace(payload=payload))
    CacheService(db.session).invalidate('company_facts')
    for account in (client, other):
        assert account.post('/api/v1/companies', json={'ticker':'VALX'}).status_code in (200, 201)
    rows = db.session.execute(select(Company.owner_id, FinancialMetric.value).join(FinancialMetric)
                              .where(Company.ticker == 'VALX',FinancialMetric.concept == 'revenue')
                              .order_by(Company.owner_id,FinancialMetric.fiscal_year.desc())).all()
    by_owner = {}
    for owner, value in rows:
        by_owner.setdefault(owner,value)
    assert list(by_owner.values()) == [2580000000.0, 2580000000.0]
