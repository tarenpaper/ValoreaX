# ValoreaX — Architecture

Local-first healthcare equity research platform. **Educational tool, not investment advice.**

## Account boundary

Supabase Auth owns email/password identities. A Flask request guard verifies signed
access tokens before all research APIs. Each company is owned by one verified user
UUID, with uniqueness on `(owner_id, ticker)`; its child records inherit that scope.
Watchlist and news-sector aggregation also filter by owner. Raw public provider
cache and benchmark prices remain shared infrastructure. Alembic migrations manage
the schema; legacy company rows remain unassigned and inaccessible through the API.
See [Authentication setup](AUTHENTICATION.md) for configuration and rollout details.

## High-level shape

```
┌────────────┐     REST /api/v1      ┌─────────────────────────────┐
│  Frontend  │  ───────────────────▶ │          Backend            │
│ React + TS │  ◀─────────────────── │      Flask + SQLAlchemy     │
│   (Vite)   │        JSON           │                             │
└────────────┘                       │  providers → services → api │
                                     └──────────────┬──────────────┘
                                                    │
                            ┌───────────────────────┴───────────────┐
                            │  SQLite (local dev) / PostgreSQL (compose) │
                            └────────────────────────────────────────┘
                                                    ▲
                                                    │ HTTP (no key)
                                     ┌──────────────┴──────────────┐
                                     │  SEC EDGAR XBRL / mock data  │
                                     └──────────────────────────────┘
```

## Backend layers

The backend is deliberately layered so each concern is testable and swappable.

1. **Providers** (`app/providers/`) — the swappable data seam.
   - `base.py` defines interfaces (`SecDataProvider`, `MarketDataProvider`, `CatalystProvider`)
     and transport dataclasses.
   - `mock_provider.py` returns Company-Facts-shaped **sample** payloads offline.
   - `sec_edgar.py` calls the real (free, keyless) SEC EDGAR endpoints.
   - `clinicaltrials.py` is the live (free, keyless) ClinicalTrials.gov v2 catalyst adapter;
     `mock_catalyst.py` mirrors its record shape offline. `manual_catalyst.py` fetches nothing.
   - `fmp_analyst.py` is the live Financial Modeling Prep analyst-coverage adapter;
     `mock_analyst.py` mirrors its shape offline.
   - `factory.py` picks each implementation from config (`SEC_PROVIDER`, `MARKET_DATA_PROVIDER`,
     `CATALYST_PROVIDER`, `ANALYST_PROVIDER`).
   - Because mock and live emit the **same** schema, one normalizer/ingestion path handles both.

2. **Services** (`app/services/`) — business logic.
   - `normalization.py` — XBRL → our concept vocabulary, with provenance + data-quality flags.
   - `ingestion_service.py` — orchestrates fetch → raw store → normalize → persist (idempotent).
   - `cache_service.py` — DB-backed TTL cache (see [CACHING.md](CACHING.md)).
   - `product_revenue.py` — per-drug revenue from 10-K XBRL (`srt:ProductOrServiceAxis`).
   - `llm_filing.py` — quote-verified pipeline, population and exclusivity extraction.
   - `drug_assets.py` — assembles drugs and derives pipeline peak sales.
   - `rnpv.py` / `rnpv_benchmarks.py` — pure per-drug rNPV engine and its labelled benchmarks.
   - `rnpv_valuation.py` — feeds the engine from stored drugs + SEC economics
     (see [VALUATION.md](VALUATION.md)).
   - `signals.py` — transparent, explainable scoring engine
     (see [SIGNALS.md](SIGNALS.md)).
   - `derivations.py` — bridges stored data → engine inputs (signal inputs, biotech profile).
   - `catalyst_ingestion.py` — fetch → cache → raw store → idempotent upsert of trial catalysts
     (preserves manual events and human-recorded outcomes).
   - `analyst_ingestion.py` — upserts an analyst consensus snapshot + per-institution ratings;
     `signals.py` gains an `analyst_consensus` component and derives its input from that
     coverage — and only that component, so one opinion cannot reach the score twice.
   - `evaluation.py` — look-ahead-safe directional-agreement scoring, shared by the
     `/signals/backtest` endpoint and the `python -m app.evaluate` scheduled job.

3. **Models** (`app/models/`) — SQLAlchemy 2.0 ORM.
   `Company`, `Filing`, `RawProviderResponse`, `FinancialMetric`, `CatalystEvent`,
   `MarketPrice`, `SignalRun`, `CacheEntry`, `ProductRevenue`, `DrugAsset`. Raw provider payloads live in their own
   table (`RawProviderResponse`) — **raw and normalized data never share a table**.

4. **API** (`app/api/`) — Flask blueprints under `/api/v1`.
   - `errors.py` — one consistent error envelope.
   - `schemas.py` — marshmallow request validation.
   - `serializers.py` — explicit output serialization (provenance always attached).
   - `v1/*.py` — one module per resource.

## Key design decisions

- **Provenance-first.** Every `FinancialMetric` carries its originating XBRL concept, filing
  accession, form, fiscal period, source, an extraction status (`reported`/`derived`/`missing`/
  `inconsistent`), and a confidence. The UI surfaces all of it.
- **Nothing fabricated.** Missing data is flagged, never invented. A drug whose peak sales
  cannot be derived from the filing is listed with its reason and no value, and a company with
  no valued drug reports no company value rather than a number.
- **Extraction is verified, not trusted.** Every value Plutus reads out of a filing carries a
  verbatim quote that must appear in the cited text; items failing the check are dropped. Sample data is clearly
  labelled `(SAMPLE)` / `source=mock` end to end.
- **Real-world XBRL handling.** The normalizer keys facts by *period-end year* (not the report
  `fy`, which mislabels comparatives), guards flow facts to ~annual durations, and merges
  candidate concepts per-year (filers switch tags over time, e.g. Pfizer).
- **Look-ahead-safe evaluation.** `SignalRun` stores an `as_of_date` + input snapshot; the
  shared `evaluation.py` service only scores catalyst outcomes that resolved *after* that date,
  so the API endpoint and the scheduled job apply one identical guard.
- **Pure, tested cores.** The rNPV and signal engines have no I/O, so they are trivially unit
  tested and reused by the seed, API, and tests alike.

## Request lifecycle (ingest example)

```
POST /api/v1/companies {ticker}
  → get_sec_provider().get_profile(ticker)          # resolve identity
  → cache.get_or_set("company_facts", cik, ttl, …)  # fetch (cached) raw XBRL
  → store RawProviderResponse (deduped by content hash)
  → normalize_company_facts(payload)                # → metrics + filings + warnings
  → persist Filings + FinancialMetrics (idempotent)
  → 201 { company, ingestion: { metric_count, warnings, … } }
```
