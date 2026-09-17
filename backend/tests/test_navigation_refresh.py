from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import BenchmarkPrice, CacheEntry, FinancialMetric
from app.providers import PricePoint, ProviderError


def test_navigation_reuses_prices_and_refreshes_after_five_minutes(client, db, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    calls = []

    class Market:
        name = 'counting'

        def get_prices(self, ticker, lookback_days):
            calls.append(ticker)
            return [PricePoint(date=datetime.now(UTC).date(), close=100 + len(calls))]

    monkeypatch.setattr('app.api.v1.prices.get_market_provider', lambda: Market())
    payload = {'view': 'watchlist'}
    first = client.post('/api/v1/navigation/refresh', json=payload)
    assert first.status_code == 200 and first.json['warnings'] == []
    assert calls == ['VALX', 'XLV']
    price = client.get('/api/v1/watchlist').json['companies'][0]['price']
    client.post('/api/v1/navigation/refresh', json=payload)
    assert calls == ['VALX', 'XLV']
    assert client.get('/api/v1/watchlist').json['companies'][0]['price'] == price
    for row in db.session.execute(select(CacheEntry)).scalars():
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.session.commit()
    client.post('/api/v1/navigation/refresh', json=payload)
    assert calls == ['VALX', 'XLV', 'VALX', 'XLV']
    assert client.get('/api/v1/watchlist').json['companies'][0]['price'] != price


def test_navigation_scopes_companies_and_rejects_unknown_view(client, app, token_for):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    other = app.test_client()
    other.environ_base['HTTP_AUTHORIZATION'] = f"Bearer {token_for('22222222-2222-4222-8222-222222222222')}"
    assert other.post('/api/v1/navigation/refresh', json={'view': 'watchlist'}).json['results'] == []
    assert other.post('/api/v1/navigation/refresh', json={'view': 'news', 'ticker': 'VALX'}).status_code == 404
    assert client.post('/api/v1/navigation/refresh', json={'view': []}).status_code == 422
    assert app.test_client().post('/api/v1/navigation/refresh', json={'view': 'watchlist'}).status_code == 401


def test_navigation_failure_preserves_stored_prices_and_retries(client, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    client.post('/api/v1/companies/VALX/prices/sync')
    price = client.get('/api/v1/watchlist').json['companies'][0]['price']
    calls = []

    def fail():
        calls.append(True)
        raise ProviderError('Provider unavailable')

    monkeypatch.setattr('app.api.v1.prices.get_market_provider', fail)
    for _ in range(2):
        result = client.post('/api/v1/navigation/refresh', json={'view': 'watchlist'})
        assert result.status_code == 200
        assert 'Provider unavailable' in result.json['warnings'][0]
    assert len(calls) == 2
    assert client.get('/api/v1/watchlist').json['companies'][0]['price'] == price


def test_source_cache_hits_do_not_extend_expiry(db, monkeypatch):
    from app.services.navigation_refresh import NavigationCache

    cache = NavigationCache(db.session)
    cache.set('news', 'provider:VALX', {'items': [1]}, 99999)
    entry = db.session.execute(select(CacheEntry)).scalar_one()
    expires = entry.expires_at.replace(tzinfo=UTC)
    later = expires - timedelta(seconds=45)
    monkeypatch.setattr('app.services.navigation_refresh.utcnow', lambda: later)
    monkeypatch.setattr('app.services.cache_service.utcnow', lambda: later)
    next_cache = NavigationCache(db.session)
    assert next_cache.get('news', 'provider:VALX') == {'items': [1]}
    assert next_cache.remaining == 45
    assert entry.expires_at.replace(tzinfo=UTC) == expires
    monkeypatch.setattr('app.services.cache_service.utcnow', lambda: expires)
    assert next_cache.get('news', 'provider:VALX') is None


def test_watchlist_refresh_skips_unwatched_companies(client, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    client.post('/api/v1/companies', json={'ticker': 'CARO'})
    assert client.delete('/api/v1/watchlist/CARO').status_code == 200
    calls = []

    class Market:
        name = 'counting'

        def get_prices(self, ticker, lookback_days):
            calls.append(ticker)
            return [PricePoint(date=datetime.now(UTC).date(), close=10)]

    monkeypatch.setattr('app.api.v1.prices.get_market_provider', lambda: Market())
    result = client.post('/api/v1/navigation/refresh', json={'view': 'watchlist'})
    assert result.status_code == 200 and result.json['warnings'] == []
    assert calls == ['VALX', 'XLV']


def test_price_sync_does_not_wipe_shared_benchmark(client, db, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    client.post('/api/v1/companies', json={'ticker': 'CARO'})
    calls = []

    class Market:
        name = 'counting'

        def get_prices(self, ticker, lookback_days):
            calls.append(ticker)
            return [PricePoint(date=datetime.now(UTC).date(), close=100 + len(calls))]

    monkeypatch.setattr('app.api.v1.prices.get_market_provider', lambda: Market())
    assert client.post('/api/v1/companies/VALX/prices/sync').status_code == 201
    first = db.session.execute(
        select(func.count()).select_from(BenchmarkPrice).where(BenchmarkPrice.symbol == 'XLV')
    ).scalar()
    assert client.post('/api/v1/companies/CARO/prices/sync').status_code == 201
    second = db.session.execute(
        select(func.count()).select_from(BenchmarkPrice).where(BenchmarkPrice.symbol == 'XLV')
    ).scalar()
    assert first == second == 1
    assert calls == ['VALX', 'XLV', 'CARO']


def test_cached_ingest_does_not_rewrite_metrics(client, db):
    created = client.post('/api/v1/companies', json={'ticker': 'VALX'}).get_json()
    company_id = created['company']['id']
    ids = set(db.session.execute(
        select(FinancialMetric.id).where(FinancialMetric.company_id == company_id)
    ).scalars())
    again = client.post('/api/v1/companies', json={'ticker': 'VALX'}).get_json()
    assert again['ingestion']['was_cached'] is True
    assert again['ingestion']['metric_count'] == len(ids)
    assert set(db.session.execute(
        select(FinancialMetric.id).where(FinancialMetric.company_id == company_id)
    ).scalars()) == ids


def test_providers_are_reused_for_the_configured_name(app):
    from app.providers import get_market_provider, get_sec_provider

    with app.app_context():
        assert get_sec_provider() is get_sec_provider()
        assert get_market_provider() is get_market_provider()
