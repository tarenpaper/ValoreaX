# Data sources & providers

## Provider selection

Set `SEC_PROVIDER` in the environment:

| value       | behaviour                                                                 |
| ----------- | ------------------------------------------------------------------------- |
| `mock`      | Offline, deterministic **sample** data (default). Tickers: VALX, HELX, CARO. |
| `sec_edgar` | Live SEC EDGAR XBRL for any US filer. Free, **no API key**.               |

Swap or add a source by implementing `SecDataProvider` (see `app/providers/base.py`) and
registering it in `app/providers/factory.py`. Nothing else changes.

## SEC EDGAR (live adapter)

Uses three public, keyless endpoints:

- `https://www.sec.gov/files/company_tickers.json` — ticker → CIK map (cached in-process).
- `https://data.sec.gov/submissions/CIK##########.json` — profile (name, SIC, exchange).
- `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` — the XBRL company facts.

**Fair-access policy:** SEC requires a descriptive `User-Agent` containing contact info and
rate-limits to ~10 req/s. Set `SEC_USER_AGENT="YourApp your-email@example.com"`. The adapter
refuses to run with a placeholder value.

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

## Market prices (`MarketDataProvider`)

The default `mock` provider remains deterministic, offline **sample** data for development and
tests. A real adapter is available through `MARKET_DATA_PROVIDER=alpha_vantage`:

```bash
MARKET_DATA_PROVIDER=alpha_vantage
ALPHA_VANTAGE_API_KEY=your_key_here
MARKET_BENCHMARK_TICKER=XLV
MARKET_PRICE_LOOKBACK_DAYS=90
MARKET_EVENT_WINDOW_TRADING_DAYS=5
```

The adapter calls Alpha Vantage's documented `TIME_SERIES_DAILY` endpoint and stores recent
unadjusted daily close/volume observations for both the issuer and the configured benchmark.
The compact response is limited to the most recent 100 trading sessions, so this MVP supports
recent catalyst-event windows only. The application never presents these close-based calculations
as total returns or a market-model alpha.

### Abnormal-return methodology

`GET /companies/{id}/prices/abnormal-return?event_date=YYYY-MM-DD` calculates the issuer's
close-to-close return less the benchmark's return. The window starts at the close before the first
trading session on or after the event date and ends five trading sessions later by default. Price
dates are aligned before calculation; the request fails honestly when the complete window is not
available. Signals auto-derive this event-window excess return for the latest fully observable
resolved catalyst, or otherwise use a 20-trading-day benchmark-adjusted return.

## Catalysts (`CatalystProvider`)

MVP catalysts are **manually entered** via the CRUD API — we do not scrape inaccessible sources
or invent events. `ManualCatalystProvider` satisfies the interface (fetches nothing) so a future
authorized adapter (e.g. an authorized ClinicalTrials.gov client) can drop in without API changes.
