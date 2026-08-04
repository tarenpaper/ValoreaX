"""Application configuration, sourced entirely from environment variables.

No secrets are hard-coded. Local development falls back to a SQLite file so the
app runs with zero external services; Docker Compose injects a Postgres URL.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    """Runtime configuration resolved from environment variables."""

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")

    # Database — default to a local SQLite file for frictionless local dev.
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "sqlite:///valorea.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = field(default_factory=dict)

    # SEC data provider wiring.
    SEC_PROVIDER: str = os.getenv("SEC_PROVIDER", "mock")
    SEC_USER_AGENT: str = os.getenv("SEC_USER_AGENT", "ValoreaX-Research example@example.com")
    SEC_BASE_URL: str = os.getenv("SEC_BASE_URL", "https://data.sec.gov")
    SEC_WWW_URL: str = os.getenv("SEC_WWW_URL", "https://www.sec.gov")

    # Market data is mock by default so an API key is never required to run tests.
    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "mock")
    TWELVE_DATA_API_KEY: str = os.getenv("TWELVE_DATA_API_KEY", "")
    TWELVE_DATA_BASE_URL: str = os.getenv("TWELVE_DATA_BASE_URL", "https://api.twelvedata.com")
    MARKET_BENCHMARK_TICKER: str = os.getenv("MARKET_BENCHMARK_TICKER", "XLV").upper()
    MARKET_PRICE_LOOKBACK_DAYS: int = field(
        default_factory=lambda: _int("MARKET_PRICE_LOOKBACK_DAYS", 90)
    )
    MARKET_EVENT_WINDOW_TRADING_DAYS: int = field(
        default_factory=lambda: _int("MARKET_EVENT_WINDOW_TRADING_DAYS", 5)
    )
    MARKET_DATA_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: _int("MARKET_DATA_TIMEOUT_SECONDS", 20)
    )

    # Cache TTLs (seconds). See docs/CACHING.md for the invalidation strategy.
    CACHE_TTL_COMPANY_FACTS: int = field(default_factory=lambda: _int("CACHE_TTL_COMPANY_FACTS", 86_400))
    CACHE_TTL_MARKET_PRICE: int = field(default_factory=lambda: _int("CACHE_TTL_MARKET_PRICE", 900))

    # CORS: which browser origin may call the API.
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    ENV: str = os.getenv("FLASK_ENV", "development")

    def as_flask_mapping(self) -> dict:
        """Return only the keys Flask/Flask-SQLAlchemy read from app.config."""
        mapping = {
            "SECRET_KEY": self.SECRET_KEY,
            "SQLALCHEMY_DATABASE_URI": self.SQLALCHEMY_DATABASE_URI,
            "SQLALCHEMY_TRACK_MODIFICATIONS": self.SQLALCHEMY_TRACK_MODIFICATIONS,
            "SEC_PROVIDER": self.SEC_PROVIDER,
            "SEC_USER_AGENT": self.SEC_USER_AGENT,
            "SEC_BASE_URL": self.SEC_BASE_URL,
            "SEC_WWW_URL": self.SEC_WWW_URL,
            "MARKET_DATA_PROVIDER": self.MARKET_DATA_PROVIDER,
            "TWELVE_DATA_API_KEY": self.TWELVE_DATA_API_KEY,
            "TWELVE_DATA_BASE_URL": self.TWELVE_DATA_BASE_URL,
            "MARKET_BENCHMARK_TICKER": self.MARKET_BENCHMARK_TICKER,
            "MARKET_PRICE_LOOKBACK_DAYS": self.MARKET_PRICE_LOOKBACK_DAYS,
            "MARKET_EVENT_WINDOW_TRADING_DAYS": self.MARKET_EVENT_WINDOW_TRADING_DAYS,
            "MARKET_DATA_TIMEOUT_SECONDS": self.MARKET_DATA_TIMEOUT_SECONDS,
            "CACHE_TTL_COMPANY_FACTS": self.CACHE_TTL_COMPANY_FACTS,
            "CACHE_TTL_MARKET_PRICE": self.CACHE_TTL_MARKET_PRICE,
            "FRONTEND_ORIGIN": self.FRONTEND_ORIGIN,
            "ENV": self.ENV,
        }
        if self.SQLALCHEMY_ENGINE_OPTIONS:
            mapping["SQLALCHEMY_ENGINE_OPTIONS"] = self.SQLALCHEMY_ENGINE_OPTIONS
        return mapping


class TestConfig(Config):
    """In-memory database and mock providers for the test suite."""

    def __init__(self) -> None:
        super().__init__()
        from sqlalchemy.pool import StaticPool

        self.SQLALCHEMY_DATABASE_URI = "sqlite://"
        self.SQLALCHEMY_ENGINE_OPTIONS = {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        }
        self.SEC_PROVIDER = "mock"
        self.MARKET_DATA_PROVIDER = "mock"
        self.ENV = "testing"
