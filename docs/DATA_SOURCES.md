# Data sources & providers

## Provider selection

Set `SEC_PROVIDER` in the environment:

| value       | behaviour                                                                 |
| ----------- | ------------------------------------------------------------------------- |
| `mock`      | Offline, deterministic **sample** data (default). Tickers: VALX, HELX, CARO. VALX also carries a fictional 10-K, so drug modelling runs with no network access. |
| `sec_edgar` | Live SEC EDGAR XBRL for any US filer. Free, **no API key**.               |

Swap or add a source by implementing `SecDataProvider` (see `app/providers/base.py`) and
registering it in `app/providers/factory.py`. Nothing else changes.

## SEC EDGAR (live adapter)

Uses public, keyless endpoints:

- `https://www.sec.gov/files/company_tickers.json` — ticker → CIK map (cached in-process).
- `https://data.sec.gov/submissions/CIK##########.json` — profile (name, SIC, exchange), and
  the newest 10-K's accession number.
- `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` — the XBRL company facts.
- the 10-K's own documents, via its filing-index JSON: the XBRL instance (`*_htm.xml`), the
  label and definition linkbases, and the primary HTML document.

**Fair-access policy:** SEC requires a descriptive `User-Agent` containing contact info and
rate-limits to ~10 req/s. Set `SEC_USER_AGENT="YourApp your-email@example.com"`. The adapter
refuses to run with a placeholder value.

### Per-drug detail (10-K documents, not company facts)

Company facts carries only non-dimensional totals, so it can never say what one drug earned.
Revenue per drug comes from the 10-K's XBRL instance on `srt:ProductOrServiceAxis`, and the
pipeline, patient populations and patent expiry dates come from the filing's own text. Filings
never change, so all of it is keyed on the accession number and re-read only when the company
files a new 10-K. See [VALUATION.md](VALUATION.md) for the parsing hazards this had to survive
(therapeutic-area parents containing their products, aggregate lines, tag variants, flattened
patent tables) and for how extracted text is quote-verified.

### Normalization notes (real-world XBRL is messy)

The normalizer (`app/services/normalization.py`) was hardened against real filings:

- **Period keying.** A 10-K tags prior-year comparatives with the *report's* `fy`. We therefore
  key annual values by the **period-end year**, not `fy`.
- **Duration guard.** Flow facts must span ~300–400 days to count as annual (excludes
  quarters/YTD stubs occasionally tagged `fp=FY`).
- **Tag switching.** Filers change concepts over time (e.g. Pfizer moved from
  `RevenueFromContractWithCustomer…` to `Revenues`). Candidate concepts are **merged per-year**,
  highest priority filling each year.
- **Derivations.** EBITDA = operating income + D&A; total debt = long-term + current portions;
  operating income falls back to `GrossProfit − OperatingExpenses` or `Revenues − CostsAndExpenses`
  when `OperatingIncomeLoss` isn't tagged. All derivations are flagged `derived`.
- **Honest gaps.** Some filers don't tag operating income at all (e.g. JNJ) — it is reported as
  `missing` with a warning, never fabricated.

Verified against PFE, JNJ, MRNA, ABBV, LLY.

### Cash economics (biotech figures)

Normalized alongside the concepts above, and used by `app/services/biotech_profile.py`:

| Concept | Tags (priority order) | Notes |
|---|---|---|
| `operating_cash_flow` | `NetCashProvidedByUsedInOperatingActivities`, `…ContinuingOperations` | |
| `capex` | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireOtherPropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets` | Eli Lilly files total capex only under the "Other" tag |
| `marketable_securities_current` | `MarketableSecuritiesCurrent`, `AvailableForSaleSecuritiesDebtSecuritiesCurrent`, `ShortTermInvestments` | stored only when reported |
| `marketable_securities_noncurrent` | `MarketableSecuritiesNoncurrent`, `AvailableForSaleSecuritiesDebtSecuritiesNoncurrent` | stored only when reported |
| `research_development` | `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost`, `ResearchAndDevelopmentExpense` | Vertex switched tags in 2020 |
| `sga` | `SellingGeneralAndAdministrativeExpense`, `GeneralAndAdministrativeExpense` | Moderna files G&A only |

- **Derived:** free cash flow = operating cash flow − capex; liquidity = cash + current and
  non-current marketable securities.
- **Excluded on purpose:** `LongTermInvestments` (includes illiquid equity stakes) and combined
  cash-plus-investments totals (would double count against cash).
- **Absent securities are not a gap.** Many companies hold none, so no `missing` row or warning
  is written for them; liquidity notes that it is cash only.
- **Column length.** `financial_metrics.xbrl_concept` is `VARCHAR(128)`, which PostgreSQL enforces
  and SQLite does not. Derived provenance that would exceed it is stored in a compact form with
  the exact component list in the quality note.
- **Not in company facts:** product-level revenue. The company-facts API carries no dimensional
  (segment/product) data, so per-drug figures such as peak sales cannot come from this source.

### Stage-aware dashboard figures

`build_profile` classifies each company by economics and picks its six headline figures:

- **Pre-revenue** — revenue missing or below 10% of R&D + SG&A (`PRE_REVENUE_SPEND_RATIO`, a
  documented judgement call). Leads with runway, liquidity, burn and dilution.
- **Revenue-generating, cash-burning** — material revenue, negative operating cash flow.
- **Cash-generative** — positive operating cash flow. Runway is shown as not meaningful.

Runway is liquidity ÷ (−operating cash flow ÷ 4). It replaced cash ÷ (−operating loss ÷ 4), which
understated runway twice over: it ignored marketable securities, and operating loss includes
non-cash costs such as stock-based compensation. For Moderna FY2025 the old formula gave 3.4
quarters and the new one 17.4. The signal engine's `cash_runway_quarters` input uses the same
function, so the correction also stops well-funded companies being scored as financing risks.
Metrics stored before these concepts existed fall back to cash and operating loss, with reduced
confidence and a note, until the company is refreshed.

FCF margin and R&D intensity are withheld as not meaningful for pre-revenue companies.

## Market prices (`MarketDataProvider`)

The default `mock` provider remains deterministic, offline **sample** data for development and
tests. A real adapter is available through `MARKET_DATA_PROVIDER=twelve_data`:

```bash
MARKET_DATA_PROVIDER=twelve_data
TWELVE_DATA_API_KEY=your_key_here
MARKET_BENCHMARK_TICKER=XLV
MARKET_PRICE_LOOKBACK_DAYS=90
MARKET_EVENT_WINDOW_TRADING_DAYS=5
```

The adapter calls Twelve Data's documented `/time_series` endpoint with a `1day` interval and
stores recent daily close/volume observations for both the issuer and the configured benchmark.
The configured lookback is capped at 5,000 observations, and this MVP is intended for recent
catalyst-event windows. The application never presents these close-based calculations as total
returns or a market-model alpha.

### Abnormal-return methodology

`GET /companies/{id}/prices/abnormal-return?event_date=YYYY-MM-DD` calculates the issuer's
close-to-close return less the benchmark's return. The window starts at the close before the first
trading session on or after the event date and ends five trading sessions later by default. Price
dates are aligned before calculation; the request fails honestly when the complete window is not
available. Signals auto-derive this event-window excess return for the latest fully observable
resolved catalyst, or otherwise use a 20-trading-day benchmark-adjusted return.

## Catalysts (`CatalystProvider`)

Set `CATALYST_PROVIDER` in the environment:

| value            | behaviour                                                                        |
| ---------------- | -------------------------------------------------------------------------------- |
| `manual`         | CRUD API only, **offline** (default). `ManualCatalystProvider` fetches nothing.   |
| `mock`           | Deterministic **sample** trial catalysts (offline; used by the test suite).       |
| `clinicaltrials` | Live [ClinicalTrials.gov v2](https://clinicaltrials.gov/data-api/api) — free, **no key**. |

Only `clinicaltrials` makes outbound calls, so the default install and the tests stay offline.
Manual entry via the CRUD API works regardless of this setting.

### ClinicalTrials.gov (live adapter)

`app/providers/clinicaltrials.py` queries `GET https://clinicaltrials.gov/api/v2/studies?query.spons=<company name>`
and maps each study to a catalyst via the pure, unit-tested `_map_study` helper:

- **Milestone → date.** `expected_date` uses the primary-completion date (a topline-readout proxy),
  falling back to overall completion, then study start. Partial dates (`YYYY`, `YYYY-MM`) are padded
  and their precision retained in the record's `extra`.
- **Event type.** Data-generating phases (Phase 1–3) map to `phase_readout`; others to `trial_completion`.
- **Outcomes are never inferred.** Every ingested catalyst is `outcome="pending"` with no `actual_date` —
  a scheduled date is *not* a result. Positive/negative resolutions stay a human, manual act.

**Sponsor matching is by name** (`Company.name`), which is approximate — biotech legal names differ
from CT.gov sponsor strings. Ingestion attaches a warning and retains the raw pull in
`RawProviderResponse` (`resource_type="clinical_trials"`) so every match can be audited by NCT id.

### Ingestion & idempotency

`POST /companies/{id}/catalysts/ingest` runs the configured provider and upserts events keyed on
`(company_id, source, external_id)` (the NCT id). Re-running refreshes scheduling fields in place —
never duplicating, and **never overwriting a human-recorded `actual_date`/`outcome`**. The fetch is
cached (`CACHE_TTL_CLINICAL_TRIALS`, default 6h). A polite `CLINICALTRIALS_USER_AGENT` with contact
info is sent, matching the SEC posture.

## Analyst coverage (`AnalystDataProvider`)

Set `ANALYST_PROVIDER` in the environment:

| value  | behaviour                                                                    |
| ------ | ---------------------------------------------------------------------------- |
| `mock` | Deterministic **sample** coverage (offline; used by the test suite).          |
| `fmp`  | Live [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs) — needs `FMP_API_KEY`. |

The signal engine is **guided by analysts**: the rating distribution drives a
dedicated `analyst_consensus` component (25% weight), and the consensus price
target auto-fills the signal's `valuation_upside` when the user hasn't supplied one.

### FMP (live adapter)

`app/providers/fmp_analyst.py` assembles coverage from several FMP **`/stable/`**
endpoints (the legacy `/api/v3` + `/api/v4` paths are rejected for keys issued after
FMP's 2025 migration), each fetched *tolerantly* so one premium/empty endpoint
doesn't sink the pull:

- `/stable/grades-consensus?symbol=…` → rating distribution + consensus label
  (falls back to `/stable/grades-historical` if unavailable)
- `/stable/price-target-consensus?symbol=…` → target high/low/consensus/median
- `/stable/quote?symbol=…` → current price (for implied upside)
- `/stable/grades?symbol=…` → recent per-institution grades

All parsing lives in pure `_map_*` / `consensus_label` helpers (unit-tested against
fixtures). Ratings are third-party **opinions**, clearly labelled as such — nothing
is fabricated, and any endpoint the plan doesn't cover is left null with a warning.
Some endpoints require a paid FMP plan; the adapter degrades to whatever is available.

### Ingestion

`POST /companies/{id}/analysts/ingest` upserts one `AnalystConsensus` snapshot plus a
fresh set of per-institution `AnalystRating` rows (raw pull retained in
RawProviderResponse, `resource_type="analyst"`). `GET /companies/{id}/analysts`
returns the stored consensus + institutions for the dashboard.

## News (`NewsProvider`)

Set `NEWS_PROVIDER` in the environment:

| value     | behaviour                                                                 |
| --------- | ------------------------------------------------------------------------- |
| `mock`    | Deterministic **sample** headlines with a spread of sentiment (offline).   |
| `finnhub` | Live [Finnhub company-news](https://finnhub.io/docs/api/company-news) — free tier, needs `FINNHUB_API_KEY`. |

### Sentiment, impact & tags are a labeled heuristic

Finnhub's free company-news has no per-article sentiment, so
`app/services/news_analysis.py` computes it with a **transparent keyword heuristic**
(bullish/bearish term balance → label + score), plus a coarse impact tier and topic
tags. Every value is stored with `sentiment_method` (`heuristic` or `provider`) and
surfaced in the UI as *heuristic — not verified* — it is never presented as real
analyst sentiment. If a provider supplies sentiment, that is used and labeled
`provider`.

### Composite view

`POST /companies/{id}/news/ingest` fetches → caches → analyzes → upserts articles
(idempotent per article; raw pull retained in RawProviderResponse,
`resource_type="news"`). `GET /companies/{id}/news` returns everything the News
Intelligence page needs in one request: the analyzed article stream, a **catalyst
correlation matrix** (news volume + avg sentiment per pipeline asset — matched by
drug name, **brand↔generic aliases** e.g. "Casgevy"⇄"exagamglogene autotemcel"
(`app/services/drug_aliases.py`), combination components, and specific indication
keywords, all shown in each row's `match_terms`), trending topic tags, an app-wide **sector
sentiment** roll-up, and the price series + event markers for the reaction chart.

Each article also gets a **clinical-relevance** score (trial/regulatory keywords, with a
strong bonus when it names one of the company's pipeline assets). Clinical articles are
surfaced to the top of the stream, can be isolated with the "Clinical only" filter, and are
the *only* news events marked on the reaction chart (dot size scales with relevance) — so
general market chatter doesn't bury, or clutter the chart around, actual trial news. The
score is a labeled heuristic.

## Evaluation loop

`app/services/evaluation.py` scores each persisted signal's direction against the first catalyst
outcome that resolved **after** the signal's `as_of_date` (the look-ahead guard). It backs both the
`/signals/backtest` endpoint and the scheduled job:

```bash
python -m app.evaluate                 # every company (text report)
python -m app.evaluate --company VALX   # one ticker
python -m app.evaluate --json           # machine-readable
```

Point cron / Windows Task Scheduler at that command to run it periodically. It remains a
directional-agreement scaffold — when no post-signal catalysts have resolved, the rate is honestly
`null`, never a fabricated figure.
