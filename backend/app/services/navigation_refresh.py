"""Refresh sidebar sources on demand, with five-minute DB-backed freshness."""
from flask import current_app

from app.extensions import db
from app.models.common import utcnow
from app.providers import get_analyst_provider, get_catalyst_provider, get_news_provider
from app.services import CacheService, ingest_company
from app.services.analyst_ingestion import ingest_analyst_data
from app.services.catalyst_ingestion import ingest_catalysts
from app.services.news_ingestion import ingest_news

TTL = 300


class NavigationCache(CacheService):
    """Separate short-lived provider payloads from older long-lived ingest caches."""
    def __init__(self, session):
        super().__init__(session)
        self.remaining = TTL

    def get(self, namespace, key):
        value = super().get(f"nav_{namespace}", key)
        if value is not None and self.last_ttl_remaining is not None:
            self.remaining = min(self.remaining, self.last_ttl_remaining)
        return value

    def set(self, namespace, key, value, ttl, provider=None):
        return super().set(f"nav_{namespace}", key, value, TTL, provider)


def refresh_source(company, source):
    from app.api.v1.prices import sync_prices

    config = current_app.config
    cache = CacheService(db.session)
    providers = ':'.join(str(config.get(k)) for k in (
        'SEC_PROVIDER', 'MARKET_DATA_PROVIDER', 'MARKET_BENCHMARK_TICKER',
        'CATALYST_PROVIDER', 'ANALYST_PROVIDER', 'NEWS_PROVIDER'))
    key = f"{company.owner_id}:{company.id}:{source}:{providers}"
    # Avoid extending the shared price payload's own five-minute clock.
    if source == 'prices':
        response, _ = sync_prices(company.ticker)
        return {'source': source, **response.get_json()}
    cached = cache.get('navigation_refresh', key)
    if cached is not None:
        return {**cached, 'cached': True}
    short_cache = NavigationCache(db.session)
    if source == 'financials':
        ingest_company(db.session, company.ticker, short_cache, config, owner_id=company.owner_id)
    elif source == 'catalysts':
        ingest_catalysts(db.session, company, get_catalyst_provider(), short_cache, config)
    elif source == 'analysts':
        ingest_analyst_data(db.session, company, get_analyst_provider(), short_cache, config)
    elif source == 'news':
        ingest_news(db.session, company, get_news_provider(), short_cache, config)
    value = {'ticker': company.ticker, 'source': source, 'refreshed_at': utcnow().isoformat()}
    cache.set('navigation_refresh', key, value, short_cache.remaining)
    return {**value, 'cached': False}
