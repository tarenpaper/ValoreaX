from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import CacheEntry
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
