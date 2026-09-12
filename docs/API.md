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
| GET    | `/companies/{id}/summary`     | Dashboard: profile + latest key metrics + DQ warnings.  |
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

## Valuation

| Method | Path                          | Description                              |
| ------ | ----------------------------- | ---------------------------------------- |
| POST   | `/companies/{id}/valuation`   | Run base/bull/bear DCF + sensitivity.    |

**Request:**
```json
{
  "assumptions": {
    "revenue_growth": 0.15, "operating_margin": 0.12, "tax_rate": 0.21,
    "capex_pct_revenue": 0.05, "nwc_pct_revenue": 0.05,
    "wacc": 0.11, "terminal_growth": 0.03, "projection_years": 5
  },
  "inputs": { "base_revenue": 1.29e9, "net_debt": -7.3e8, "shares_outstanding": 2.4e8 },
  "include_sensitivity": true
}
```
`inputs` is optional — omitted values are derived from stored SEC metrics. The response
separates `inputs` (with per-field `sources`: `sec`/`override`/`default`), `assumptions`
(user-entered), and `scenarios` (calculated EV, equity value, implied price, projections).
Invalid assumptions (e.g. WACC ≤ terminal growth) → 422.

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

## Signals

| Method | Path                                       | Description                                  |
| ------ | ------------------------------------------ | -------------------------------------------- |
| POST   | `/companies/{id}/signals`                  | Score + (optionally) persist a signal.       |
| GET    | `/companies/{id}/signals`                  | Signal run history.                          |
| GET    | `/companies/{id}/signals/backtest`         | Directional-agreement scaffold (look-ahead-safe). |

**Signal request (all fields optional; gaps auto-derived when `auto_derive`):**
```json
{
  "valuation_upside": 0.28, "catalyst_outcome": "positive", "event_type": "pdufa",
  "days_to_next_catalyst": 20, "abnormal_return": 0.08, "cash_runway_quarters": 10,
  "manual_confidence": 0.7, "as_of_date": "2026-08-03",
  "auto_derive": true, "persist": true
}
```
**Response** returns `signal` (`long`/`short`/`watchlist`), `score`, `confidence`, a per-input
`components` breakdown (each with `contribution`, `weight`, `explanation`), a readable
`rationale`, `auto_derived` sources, and `persisted_run_id`.

The **backtest** reports `directional_agreement_rate` **only when real post-signal outcomes
exist** — otherwise `null` (no fabricated performance figure).
# Authentication

The new historical investment API is `POST /api/v1/companies/<identifier>/backtest`
with `start_date`, `end_date`, and `investment`. See [Backtesting](BACKTESTING.md)
for accounting assumptions, historical trend rules, and data coverage checks.

All `/api/v1` endpoints except `GET /api/v1/health` require
`Authorization: Bearer <Supabase access token>`. `GET /api/v1/auth/me` returns the
verified account ID and email. Company IDs/tickers and all research endpoints are
scoped to that account; another account's record returns 404. See
[Authentication setup](AUTHENTICATION.md).
