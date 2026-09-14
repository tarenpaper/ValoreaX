# ValoreaX

Select a public healthcare company,
ingest and normalize its SEC financials, model DCF valuations, track clinical/FDA catalysts, and
produce **transparent, explainable** research signals.

> ⚠️ **Educational research tool — not investment advice.** Outputs are illustrative, never
> guaranteed returns. Some data is clearly-labelled **sample** data. Always verify against
> primary SEC filings. No fabricated financial, catalyst, or analyst data is presented as real.

---

## What's inside

| Area | Highlights |
| ---- | ---------- |
| **Dashboard** | Ticker search, company profile, latest revenue/cash/debt/shares/filing date, and a provenance-rich financial-input table (source · period · units · extraction status/confidence). |
| **SEC ingestion** | Provider interface with a **live SEC EDGAR XBRL adapter (keyless)** and a deterministic offline **mock**. Raw payloads stored separately from normalized values; every value keeps filing accession, form, fiscal period, and concept name. |
| **Data layer** | SQLAlchemy models for Company, Filing, RawProviderResponse, FinancialMetric, CatalystEvent, MarketPrice, SignalRun, CacheEntry + a documented DB-backed TTL cache. |
| **Valuation** | Tested DCF with base/bull/bear scenarios, sensitivity grid, and clear separation of SEC-derived inputs vs. user assumptions vs. calculated outputs. |
| **Catalysts** | Full CRUD for clinical/FDA events + a company timeline. Manual entry **plus** an optional live [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) adapter (keyless) behind the `CatalystProvider` interface — idempotent upsert that ingests trial *dates* as `pending` and never overwrites human-recorded outcomes. |
| **Analysts** | Analyst coverage from covering institutions — a consensus rating distribution + price targets via an optional live [Financial Modeling Prep](https://site.financialmodelingprep.com/) adapter (or a deterministic mock) behind an `AnalystDataProvider` interface. The panel shows the Buy/Hold/Sell split, target range, implied upside, and per-institution grades. |
| **News** | A News Intelligence dashboard: a live company-news stream ([Finnhub](https://finnhub.io/) adapter or mock) with **labeled-heuristic** sentiment/impact/tags (never presented as verified), a catalyst→news correlation matrix, trending topics, sector-sentiment roll-up, and a price-reaction chart with news/catalyst markers. |
| **Signals** | Explainable LONG/SHORT/WATCHLIST scoring — every input's weighted contribution is shown. **Guided by analysts:** the consensus rating drives a dedicated component and the mean target auto-fills the valuation upside. Runs are persisted with an input snapshot + `as_of_date`; a look-ahead-safe evaluation (shared by the `/backtest` API and a `python -m app.evaluate` job) measures directional agreement. |

Full details in [`docs/`](docs/): [Architecture](docs/ARCHITECTURE.md) ·
[API reference](docs/API.md) · [Caching](docs/CACHING.md) · [Data sources](docs/DATA_SOURCES.md).

## Personal accounts

**Live sources:** provider defaults now select live adapters. See
[Live data setup](docs/LIVE_DATA.md) for required API keys and retrieval limits.
The older mock-first examples below describe the optional offline mode; tests
still use that mode explicitly.

The app now requires a Supabase email/password account. Login, signup, password
recovery, and account-scoped research workspaces are implemented. Follow
[Authentication setup](docs/AUTHENTICATION.md) to configure the Supabase project,
environment variables, and database migrations before starting. New accounts begin
with an empty watchlist. Existing unassigned data is preserved and stays private.
All `/api/v1` requests except `/health` now require an `Authorization: Bearer <access_token>`
header; add it to the older curl examples below. The Vercel frontend configuration
is included, but deployment and live provider activation are separate steps.

---

## Clinical trial success ML

The Clinical Pipeline page now includes full trial-evidence ingestion and an
experimental endpoint-success model workflow. It supports timestamped registry
snapshots, reviewed outcome labels, temporal drug-family-separated evaluation,
probability calibration, and explicit abstention when a model or evidence is
missing. No trained clinical predictor is bundled. See the
[Clinical ML guide](docs/CLINICAL_ML.md) for ingestion, labeling, training, and serving.
