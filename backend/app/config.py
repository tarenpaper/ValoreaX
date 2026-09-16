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
    SUPABASE_URL: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    AUTO_CREATE_SCHEMA: bool = field(default_factory=lambda: os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true")

    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    GEMINI_MODEL: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))

    # Database — default to a local SQLite file for frictionless local dev.
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "sqlite:///valorea.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = field(default_factory=dict)

    # SEC data provider wiring.
    SEC_PROVIDER: str = os.getenv("SEC_PROVIDER", "sec_edgar")
    SEC_USER_AGENT: str = os.getenv("SEC_USER_AGENT", "ValoreaX-Research example@example.com")
    SEC_BASE_URL: str = os.getenv("SEC_BASE_URL", "https://data.sec.gov")
    SEC_WWW_URL: str = os.getenv("SEC_WWW_URL", "https://www.sec.gov")

    # Market data is mock by default so an API key is never required to run tests.
    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "twelve_data")
    TWELVE_DATA_API_KEY: str = os.getenv("TWELVE_DATA_API_KEY", "")
    TWELVE_DATA_BASE_URL: str = os.getenv("TWELVE_DATA_BASE_URL", "https://api.twelvedata.com")
    MARKET_BENCHMARK_TICKER: str = os.getenv("MARKET_BENCHMARK_TICKER", "XLV").upper()
    MARKET_PRICE_LOOKBACK_DAYS: int = field(
        default_factory=lambda: _int("MARKET_PRICE_LOOKBACK_DAYS", 90)
    )
    MARKET_EVENT_WINDOW_TRADING_DAYS: int = field(
        default_factory=lambda: _int("MARKET_EVENT_WINDOW_TRADING_DAYS", 5)
    )
    # Each watched company needs its own daily price request, and the free market-data
    # plan allows about eight a minute — seven companies plus the benchmark.
    WATCHLIST_LIMIT: int = field(default_factory=lambda: _int("WATCHLIST_LIMIT", 7))
    MARKET_DATA_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: _int("MARKET_DATA_TIMEOUT_SECONDS", 20)
    )

    # Analyst-coverage provider wiring. Default "mock" is deterministic/offline;
    # "fmp" enables the live Financial Modeling Prep adapter (needs an API key).
    ANALYST_PROVIDER: str = os.getenv("ANALYST_PROVIDER", "fmp")
    FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
    FMP_BASE_URL: str = os.getenv("FMP_BASE_URL", "https://financialmodelingprep.com")
    FMP_TIMEOUT_SECONDS: int = field(default_factory=lambda: _int("FMP_TIMEOUT_SECONDS", 20))

    # News provider wiring. Default "mock" is deterministic/offline; "finnhub"
    # enables the live company-news adapter (needs a free Finnhub API key).
    NEWS_PROVIDER: str = os.getenv("NEWS_PROVIDER", "finnhub")
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    FINNHUB_BASE_URL: str = os.getenv("FINNHUB_BASE_URL", "https://finnhub.io/api/v1")
    FINNHUB_TIMEOUT_SECONDS: int = field(default_factory=lambda: _int("FINNHUB_TIMEOUT_SECONDS", 20))
    NEWS_LOOKBACK_DAYS: int = field(default_factory=lambda: _int("NEWS_LOOKBACK_DAYS", 30))
    NEWS_MAX_ARTICLES: int = field(default_factory=lambda: _int("NEWS_MAX_ARTICLES", 40))

    # Catalyst ingestion provider wiring. Default "manual" keeps the app offline
    # (manual CRUD only); "clinicaltrials" enables the live keyless adapter.
    CATALYST_PROVIDER: str = os.getenv("CATALYST_PROVIDER", "clinicaltrials")
    CLINICALTRIALS_BASE_URL: str = os.getenv(
        "CLINICALTRIALS_BASE_URL", "https://clinicaltrials.gov/api/v2"
    )
    CLINICALTRIALS_USER_AGENT: str = os.getenv(
        "CLINICALTRIALS_USER_AGENT", "ValoreaX-Research example@example.com"
    )
    CLINICALTRIALS_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: _int("CLINICALTRIALS_TIMEOUT_SECONDS", 20)
    )
    CLINICALTRIALS_MAX_STUDIES: int = field(
        default_factory=lambda: _int("CLINICALTRIALS_MAX_STUDIES", 25)
    )
    CLINICAL_ML_MODEL_PATH: str = field(default_factory=lambda: os.getenv("CLINICAL_ML_MODEL_PATH", ""))
    CLINICAL_ML_MAX_STUDIES: int = field(default_factory=lambda: _int("CLINICAL_ML_MAX_STUDIES", 100))

    # Cache TTLs (seconds). See docs/CACHING.md for the invalidation strategy.
    CACHE_TTL_COMPANY_FACTS: int = field(default_factory=lambda: _int("CACHE_TTL_COMPANY_FACTS", 86_400))
    CACHE_TTL_MARKET_PRICE: int = field(default_factory=lambda: _int("CACHE_TTL_MARKET_PRICE", 900))
    CACHE_TTL_CLINICAL_TRIALS: int = field(
        default_factory=lambda: _int("CACHE_TTL_CLINICAL_TRIALS", 21_600)
    )
    CACHE_TTL_ANALYST: int = field(default_factory=lambda: _int("CACHE_TTL_ANALYST", 21_600))
    CACHE_TTL_NEWS: int = field(default_factory=lambda: _int("CACHE_TTL_NEWS", 3_600))

    # CORS: which browser origin may call the API.
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    ENV: str = os.getenv("FLASK_ENV", "development")

    def as_flask_mapping(self) -> dict:
        """Return only the keys Flask/Flask-SQLAlchemy read from app.config."""
        if os.getenv("VERCEL") == "1" and self.SQLALCHEMY_DATABASE_URI.startswith("sqlite:"):
            raise RuntimeError("Vercel requires a persistent PostgreSQL DATABASE_URL")
        mapping = {
            "GEMINI_API_KEY": self.GEMINI_API_KEY,
            "GEMINI_MODEL": self.GEMINI_MODEL,
            "SUPABASE_URL": self.SUPABASE_URL,
            "AUTO_CREATE_SCHEMA": self.AUTO_CREATE_SCHEMA,
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
            "WATCHLIST_LIMIT": self.WATCHLIST_LIMIT,
            "MARKET_EVENT_WINDOW_TRADING_DAYS": self.MARKET_EVENT_WINDOW_TRADING_DAYS,
            "MARKET_DATA_TIMEOUT_SECONDS": self.MARKET_DATA_TIMEOUT_SECONDS,
            "ANALYST_PROVIDER": self.ANALYST_PROVIDER,
            "FMP_API_KEY": self.FMP_API_KEY,
            "FMP_BASE_URL": self.FMP_BASE_URL,
            "FMP_TIMEOUT_SECONDS": self.FMP_TIMEOUT_SECONDS,
            "NEWS_PROVIDER": self.NEWS_PROVIDER,
            "FINNHUB_API_KEY": self.FINNHUB_API_KEY,
            "FINNHUB_BASE_URL": self.FINNHUB_BASE_URL,
            "FINNHUB_TIMEOUT_SECONDS": self.FINNHUB_TIMEOUT_SECONDS,
            "NEWS_LOOKBACK_DAYS": self.NEWS_LOOKBACK_DAYS,
            "NEWS_MAX_ARTICLES": self.NEWS_MAX_ARTICLES,
            "CATALYST_PROVIDER": self.CATALYST_PROVIDER,
            "CLINICALTRIALS_BASE_URL": self.CLINICALTRIALS_BASE_URL,
            "CLINICALTRIALS_USER_AGENT": self.CLINICALTRIALS_USER_AGENT,
            "CLINICALTRIALS_TIMEOUT_SECONDS": self.CLINICALTRIALS_TIMEOUT_SECONDS,
            "CLINICALTRIALS_MAX_STUDIES": self.CLINICALTRIALS_MAX_STUDIES,
            "CLINICAL_ML_MODEL_PATH": self.CLINICAL_ML_MODEL_PATH,
            "CLINICAL_ML_MAX_STUDIES": self.CLINICAL_ML_MAX_STUDIES,
            "CACHE_TTL_COMPANY_FACTS": self.CACHE_TTL_COMPANY_FACTS,
            "CACHE_TTL_MARKET_PRICE": self.CACHE_TTL_MARKET_PRICE,
            "CACHE_TTL_CLINICAL_TRIALS": self.CACHE_TTL_CLINICAL_TRIALS,
            "CACHE_TTL_ANALYST": self.CACHE_TTL_ANALYST,
            "CACHE_TTL_NEWS": self.CACHE_TTL_NEWS,
            "FRONTEND_ORIGIN": self.FRONTEND_ORIGIN,
            "ENV": self.ENV,
        }
        if self.SQLALCHEMY_ENGINE_OPTIONS:
            mapping["SQLALCHEMY_ENGINE_OPTIONS"] = self.SQLALCHEMY_ENGINE_OPTIONS
        elif os.getenv("VERCEL") == "1" and self.SQLALCHEMY_DATABASE_URI.startswith(("postgresql:", "postgresql+psycopg2:")):
            from sqlalchemy.pool import NullPool

            # Supabase's pooler owns connection pooling across serverless instances.
            mapping["SQLALCHEMY_ENGINE_OPTIONS"] = {
                "poolclass": NullPool,
                "connect_args": {"sslmode": "require", "connect_timeout": 10},
            }
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
        self.CATALYST_PROVIDER = "mock"
        self.ANALYST_PROVIDER = "mock"
        self.NEWS_PROVIDER = "mock"
        self.GEMINI_API_KEY = ""
        self.ENV = "testing"
        self.AUTO_CREATE_SCHEMA = True
