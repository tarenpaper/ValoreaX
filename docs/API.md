# API reference — `/api/v1`

Base URL (local): `http://localhost:5001/api/v1`. All bodies are JSON.

## Conventions

- **Company identifier** in paths may be a numeric id or a ticker (case-insensitive).
- **Errors** always look like:
  ```json
  { "error": { "code": "not_found", "message": "…", "details": {} } }
  ```
  Codes: `bad_request` (400), `not_found` (404), `validation_error` (422),
  `upstream_error` (502), `internal_error` (500).
- **Validation** failures return HTTP 422 with per-field messages in `details`.

## Meta

| Method | Path       | Description                                   |
| ------ | ---------- | --------------------------------------------- |
| GET    | `/health`  | Liveness: `{ "status": "ok" }`.               |
| GET    | `/meta`    | Provider, disclaimer, mock tickers, cache TTL.|

## Companies

| Method | Path                          | Description                                             |
| ------ | ----------------------------- | ------------------------------------------------------- |
| GET    | `/companies?query=`           | List ingested companies (+ mock suggestions).           |
| POST   | `/companies`                  | Ingest by ticker. Body `{ "ticker": "PFE" }`. → 201.    |
| GET    | `/companies/{id}`             | Company profile + counts.                               |
| GET    | `/companies/{id}/summary`     | Dashboard: profile, latest key metrics, stage-aware `biotech_profile`, DQ warnings. |
| POST   | `/companies/{id}/refresh`     | Invalidate cache and re-ingest.                         |

**Ingest response (201):**
```json
{
  "company": { "ticker": "VALX", "name": "…", "sector": "Healthcare", "…": "…" },
  "ingestion": { "provider": "mock", "metric_count": 18, "filing_count": 3,
                 "was_cached": false, "warnings": [] }
}
```

## Financial metrics & filings

| Method | Path                                              | Description                       |
| ------ | ------------------------------------------------- | -------------------------------- |
| GET    | `/companies/{id}/metrics?concept=&fiscal_year=`   | Normalized metrics + provenance. |
| GET    | `/companies/{id}/filings`                         | Filings (accession, form, period).|

Each metric includes `value`, `unit`, `fiscal_year`, `period_end`, `source`,
`provenance{ xbrl_concept, taxonomy, accession_number, form }`, and
`quality{ status, confidence, note }`.

## Drugs and valuation

Each drug is modelled on its own and the drugs aggregate into one company value — there is no
terminal value. See [VALUATION.md](VALUATION.md) for the method.

| Method | Path                          | Description                                              |
| ------ | ----------------------------- | -------------------------------------------------------- |
| GET    | `/companies/{id}/drugs`       | Drugs with extracted values, overrides, and product lines.|
| POST   | `/companies/{id}/drugs/sync`  | Rebuild the models from the latest 10-K.                  |
| PATCH  | `/drugs/{id}`                 | Set overrides, include/exclude, or reset to the filing.   |
| POST   | `/companies/{id}/valuation`   | Run the sum-of-the-parts rNPV + sensitivity.              |

The sync is automatic and idempotent: it skips work until the company files a new 10-K, so it
is safe to call on every page load. `{"force": true}` rebuilds anyway.

**Valuation request:**
```json
{ "discount_rate": 0.10, "horizon_years": 25, "include_sensitivity": true }
```

**Valuation response** carries `assets` (each with its yearly model and per-input provenance),
`unvalued` with a stated reason, `excluded`, the waterfall (`asset_value`,
`overhead_present_value`, `net_cash`, `equity_value`, `value_per_share`), the `economics` used
with their sources, and a `sensitivity` grid over discount rate × a proportional shift in sales.

With no valued drug, `equity_value` is `null` and `note` explains why — never a fabricated
number.

**Override request** (`PATCH /drugs/{id}`):
```json
{ "overrides": { "peak_sales": 2.5e9, "loe_year": 2034 }, "included": true }
```
Overrides are stored apart from the filing's own values, so a later sync refreshes what the
filing says without discarding them. `{"reset_overrides": true}` clears them.

## Catalysts (CRUD)

| Method | Path                              | Description                     |
| ------ | --------------------------------- | ------------------------------- |
| GET    | `/companies/{id}/catalysts`       | List (ordered by expected date).|
| POST   | `/companies/{id}/catalysts`       | Create. → 201.                  |
| GET    | `/catalysts/{catalyst_id}`        | Fetch one.                      |
| PATCH  | `/catalysts/{catalyst_id}`        | Partial update.                 |
| DELETE | `/catalysts/{catalyst_id}`        | Delete.                         |

**Create body:** `drug_program` (required), `event_type` (required), `indication`,
`trial_phase`, `expected_date`, `actual_date`, `outcome`
(`pending|positive|negative|mixed|withdrawn`), `source_url`, `notes`.

## Market prices

| Method | Path                                | Description                              |
| ------ | ----------------------------------- | ---------------------------------------- |
| GET    | `/companies/{id}/prices`            | Stored issuer and benchmark price series. |
| POST   | `/companies/{id}/prices/sync`       | Refresh issuer + configured benchmark prices. → 201. |
| GET    | `/companies/{id}/prices/abnormal-return?event_date=` | Benchmark-adjusted catalyst-event return. |

## Watchlist and baskets

The watchlist is an explicit, capped set — each watched company needs its own daily price
request and the market-data plan bounds those (`WATCHLIST_LIMIT`, default 7).

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET    | `/watchlist`              | Watched companies, plus `limit` and `remaining`. |
| POST   | `/watchlist`              | Watch a ticker; ingests it only if never stored. |
| DELETE | `/watchlist/{ticker}`     | Unwatch. **Keeps** all stored data. |
| GET    | `/baskets`                | Named baskets with resolved members. |
| POST   | `/baskets`                | Create from `{name, tickers}`. |
| DELETE | `/baskets/{id}`           | Delete a basket; its companies are untouched. |
| POST   | `/baskets/{id}/activate`  | Make this basket the watchlist. |

Removing is **not** deleting: the company's filings, drug models and valuation stay, so
re-adding it costs no provider call and `GET /companies` still lists it. At the cap,
`POST /watchlist` returns **409** with `error.details.watching` naming what is in the way.

A basket's name must be an **anagram of its members' initials** — MANGO over Moderna, Amgen,
Novavax, Gilead, Organon. Each company offers two letters, its name's initial and its
ticker's, so Alphabet (GOOGL) can serve an A or a G. Order does not matter; letter counts do.
A name that does not fit is refused with 422 and a reason naming the problem letter.

## Signals

| Method | Path                                       | Description                                  |
| ------ | ------------------------------------------ | -------------------------------------------- |
| POST   | `/companies/{id}/signals`                  | Score + (optionally) persist a signal.       |
| GET    | `/companies/{id}/signals`                  | Signal run history.                          |
| GET    | `/companies/{id}/signals/backtest`         | Directional-agreement scaffold (look-ahead-safe). |

Seven weighted components, fed by the drug valuation, filings, catalysts, analyst coverage,
prices and high-impact news. See [SIGNALS.md](SIGNALS.md) for the weights, the thresholds and
what each component means.

**Signal request (all fields optional; gaps auto-derived when `auto_derive`):**
```json
{
  "valuation_upside": 0.28, "catalyst_outcome": "positive", "event_type": "pdufa",
  "days_to_next_catalyst": 20, "abnormal_return": 0.08, "cash_runway_quarters": 10,
  "fcf_margin": 0.27, "dilution_yoy": -0.01,
  "manual_confidence": 0.7, "as_of_date": "2026-08-03",
  "auto_derive": true, "persist": true
}
```
**Response** returns `signal` (`long`/`short`/`watchlist`), `score`, `confidence`, a per-input
`components` breakdown (each with `contribution`, `weight`, `explanation`, and a `basis` on the
valuation component naming the reference it used), a readable `rationale`, `auto_derived`
sources, `persisted_run_id`, and **`skipped`** — the factors that could not be computed and
why. A missing input yields no component, never a zero.

The **backtest** reports `directional_agreement_rate` **only when real post-signal outcomes
exist** — otherwise `null` (no fabricated performance figure). Because weights differ between
engine versions, it also reports `by_engine_version`; a `v3` score and a `v4` score are not
comparable.
# Authentication

The new historical investment API is `POST /api/v1/companies/<identifier>/backtest`
with `start_date`, `end_date`, and `investment`. See [Backtesting](BACKTESTING.md)
for accounting assumptions, historical trend rules, and data coverage checks.

All `/api/v1` endpoints except `GET /api/v1/health` require
`Authorization: Bearer <Supabase access token>`. `GET /api/v1/auth/me` returns the
verified account ID and email. Company IDs/tickers and all research endpoints are
scoped to that account; another account's record returns 404. See
[Authentication setup](AUTHENTICATION.md).

### Backtest benchmark comparisons

`POST /companies/<identifier>/backtest` now compares the same starting investment with
both SPY and XLV on the intersection of available trading dates. `benchmarks` contains
ending value, profit/loss, price return, CAGR (only for periods of at least a year), maximum
drawdown, and stock excess return for each ETF. Each `curve` row includes
`comparisons.SPY` and `comparisons.XLV` with `value`, `return_pct`, and `drawdown`.
Legacy singular benchmark fields refer to SPY. Missing dates are omitted and reported;
prices are never interpolated. Each distinct symbol's history retains its five-minute
cache. Dividends are excluded from all three series.
