"""API registration — mounts every v1 blueprint under /api/v1."""
from __future__ import annotations

from app.api.v1 import (
    analysts,
    backtest,
    catalysts,
    companies,
    health,
    metrics,
    navigation,
    news,
    prices,
    research,
    signals,
    valuation,
    watchlist,
)

API_PREFIX = "/api/v1"


def register_blueprints(app) -> None:
    # Company-namespaced resources.
    app.register_blueprint(companies.bp, url_prefix=f"{API_PREFIX}/companies")
    app.register_blueprint(metrics.bp, url_prefix=f"{API_PREFIX}/companies")
    app.register_blueprint(valuation.bp, url_prefix=f"{API_PREFIX}/companies")
    app.register_blueprint(prices.bp, url_prefix=f"{API_PREFIX}/companies")

    # Resources with their own top-level paths.
    app.register_blueprint(catalysts.bp, url_prefix=API_PREFIX)
    app.register_blueprint(signals.bp, url_prefix=API_PREFIX)
    app.register_blueprint(analysts.bp, url_prefix=API_PREFIX)
    app.register_blueprint(news.bp, url_prefix=API_PREFIX)
    app.register_blueprint(watchlist.bp, url_prefix=API_PREFIX)
    app.register_blueprint(health.bp, url_prefix=API_PREFIX)
    app.register_blueprint(backtest.bp, url_prefix=API_PREFIX)
    app.register_blueprint(navigation.bp, url_prefix=API_PREFIX)
    app.register_blueprint(research.bp, url_prefix=API_PREFIX)
