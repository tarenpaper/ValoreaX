"""API registration — mounts every v1 blueprint under /api/v1."""
from __future__ import annotations

from app.api.v1 import (
    catalysts,
    companies,
    health,
    metrics,
    prices,
    signals,
    valuation,
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
    app.register_blueprint(health.bp, url_prefix=API_PREFIX)
