# ValoreaX

**Local-first healthcare equity research platform.** Select a public healthcare company,
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

---

## Quick start

### Option A — Docker Compose (Postgres + backend + frontend)

```bash
cp .env.example .env      # then edit secrets (POSTGRES_PASSWORD, SECRET_KEY, SEC_USER_AGENT)
docker compose up --build
```

- Backend → http://localhost:5001  ·  Frontend → http://localhost:5173  ·  Postgres → :5432
- The backend container seeds the example company on first start.

> Note: the Compose files are provided and self-consistent but were **not executed in the build
> environment** (Docker wasn't installed there). The local path below is the verified one.

### Option B — Local (SQLite, no Docker) — *verified*

**Backend** (Python 3.12+, tested on 3.14):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed        # seed the labelled example company (VALX) into SQLite
python wsgi.py            # → http://localhost:5001
```

**Frontend** (Node 18+):

```bash
cd frontend
npm install
cp .env.example .env
npm run dev              # → http://localhost:5173
```

Open http://localhost:5173 and click **VALX** in the sidebar.

### Using live SEC data instead of the mock

```bash
# in backend/.env  (or the environment)
SEC_PROVIDER=sec_edgar
SEC_USER_AGENT=ValoreaX-Research your-email@example.com   # SEC requires real contact info
```

Then load any US ticker (e.g. `PFE`, `JNJ`, `MRNA`, `ABBV`, `LLY`) from the UI or:

```bash
curl -X POST localhost:5001/api/v1/companies -H 'Content-Type: application/json' -d '{"ticker":"PFE"}'
```

### Ingesting catalysts from ClinicalTrials.gov

Catalysts default to manual entry. To pull trial milestones from the live (keyless) API:

```bash
# in backend/.env (or the environment)
CATALYST_PROVIDER=clinicaltrials
CLINICALTRIALS_USER_AGENT=ValoreaX-Research your-email@example.com
```

```bash
curl -X POST localhost:5001/api/v1/companies/PFE/catalysts/ingest
```

Ingest is **idempotent** and matches trials by sponsor name (approximate — verify each NCT id).
Every ingested event is `outcome="pending"` (a scheduled date is not a result); manual entries and
human-recorded outcomes are never touched. Use `CATALYST_PROVIDER=mock` for offline sample catalysts.

### Analyst coverage (guides the signal)

Analyst data defaults to a deterministic mock. For live consensus ratings + price targets:

```bash
# in backend/.env (or the environment)
ANALYST_PROVIDER=fmp
FMP_API_KEY=your_key_here      # Financial Modeling Prep; kept local (gitignored)
```

```bash
curl -X POST localhost:5001/api/v1/companies/PFE/analysts/ingest
```

The signal engine then derives an `analyst_consensus` component from the rating
distribution and auto-fills `valuation_upside` from the consensus price target. In the
UI, the Signal panel's **⤓ Fetch analyst ratings** button does the same. Ratings are
third-party opinions, not advice — some FMP endpoints require a paid plan, and the
adapter degrades gracefully to whatever your tier returns.

### News intelligence

News defaults to a deterministic mock. For live company news + heuristic sentiment:

```bash
# in backend/.env (or the environment)
NEWS_PROVIDER=finnhub
FINNHUB_API_KEY=your_key_here      # free at finnhub.io; kept local (gitignored)
```

```bash
curl -X POST localhost:5001/api/v1/companies/PFE/news/ingest
```

The **News** tab then shows the article stream, a catalyst→news correlation matrix,
trending topics, sector sentiment, and a price-reaction chart. Sentiment/impact/tags
are a transparent keyword heuristic labeled *heuristic — not verified*, since Finnhub's
free tier supplies no per-article sentiment.

### Evaluating signals over time (look-ahead-safe)

Score persisted signals against catalyst outcomes that resolved *after* each signal's `as_of_date`:

```bash
python -m app.evaluate                 # all companies (text report)
python -m app.evaluate --company VALX   # one ticker
python -m app.evaluate --json           # machine-readable
```

The same guard powers `GET /api/v1/companies/<ticker>/signals/backtest`. Point cron / Task Scheduler
at the command to run it periodically. It is a directional-agreement scaffold, not a performance claim.

---

## Tests & quality

```bash
# Backend — 110 tests (valuation, signals, normalization, cache, market returns, market-data adapter,
#                       catalyst + analyst + news mapping/ingestion, signal evaluation, API integration)
cd backend && source .venv/bin/activate
pytest
ruff check app tests wsgi.py

# Frontend — type-check + production build
cd frontend
npm run typecheck
npm run build
```

**Current results:** backend `110 passed`; `ruff` clean; frontend type-checks and builds.
The normalizer is verified against live SEC data for PFE, JNJ, MRNA, ABBV, and LLY.

---

## Known limitations

1. **Real market data requires a configured provider key.** The default remains deterministic
   `mock` data for offline development and tests. Set `MARKET_DATA_PROVIDER=twelve_data` and
   `TWELVE_DATA_API_KEY` to sync recent real daily closes for a ticker and the `XLV` benchmark.
   The resulting metric is a close-to-close excess return, not a total return or market-model alpha.
2. **Operating income / EBITDA gaps for some filers.** A minority of issuers don't tag
   `OperatingIncomeLoss` (or the fallback components), e.g. JNJ. These are honestly reported as
   `missing` with a warning rather than estimated.
3. **No migrations yet.** The app calls `db.create_all()` on startup (fine for the MVP/SQLite).
   Production Postgres should adopt Alembic before schema changes.
4. **Backtest is a scaffold.** It measures directional agreement against manually-entered
   catalyst outcomes and returns a rate only when real post-signal data exists. It is **not** a
   validated performance claim, and no accuracy figure is asserted.
5. **DCF simplification.** `capex_pct_revenue` is modelled net of depreciation (so D&A isn't a
   separate line) to match the requested input set. Terminal value uses Gordon growth; deep
   out-of-model dynamics (buybacks, dilution schedules, segment build-ups) are out of scope.
6. **Docker path unverified here.** See the note under Option A.

---

## Recommended next three steps

1. **Real market data + true abnormal returns.** Implement a licensed `MarketDataProvider`
   (e.g. an authorized EOD price API), store real `MarketPrice` history, and compute abnormal
   returns vs. a sector/benchmark index so the momentum signal is meaningful.
2. **Alembic migrations + Postgres hardening.** Replace `create_all()` with versioned
   migrations, add indexes/constraints reviewed for query patterns, and wire the Compose
   Postgres path end-to-end (health-gated, seeded).
3. **Catalyst ingestion adapter + evaluation loop.** *(Delivered — see the catalyst/evaluation
   sections above.)* A keyless ClinicalTrials.gov v2 adapter now sits behind `CatalystProvider`
   with an idempotent ingest endpoint, and `python -m app.evaluate` runs the look-ahead-safe
   evaluation as a scheduled job. **Remaining:** an FDA/PDUFA calendar source (no free official
   API today), sharper sponsor→issuer matching, persisted evaluation history, and folding in
   analyst views alongside catalyst outcomes.
