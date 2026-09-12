# Live data connections

The default providers are now SEC EDGAR, Twelve Data, ClinicalTrials.gov, Financial
Modeling Prep, and Finnhub. Tests explicitly use mock providers. Docker startup no
longer seeds fictional research. Existing sample records are preserved and retain
their source labels; use real tickers for live research.

Set these server-only variables in `backend/.env` (or deployment secrets):

| Source | Required settings | Data retrieved |
| --- | --- | --- |
| SEC EDGAR | `SEC_USER_AGENT=ValoreaX-Research <contact email>` | Filed company financial facts |
| Twelve Data | `TWELVE_DATA_API_KEY` | Recent daily issuer and XLV closing prices |
| ClinicalTrials.gov | No key | Trial dates matched by sponsor |
| Financial Modeling Prep | `FMP_API_KEY` | Analyst grades, consensus, price targets |
| Finnhub | `FINNHUB_API_KEY` | Company news articles |

Restart the backend after changing settings. Docker Compose forwards all five
provider selections and keys. Keys must never go into `VITE_*` variables.

In the app, add a real US ticker and use the individual research panels to fetch
analyst coverage, trial milestones, and news. Price synchronization and financial
refresh remain available through their API endpoints.
Non-SEC feeds respect their existing cache TTLs. Source indicators show configuration
readiness, not successful connectivity or a guarantee of fresh data. A configured
key may still be invalid, rate-limited, or lack the necessary subscription entitlement.
The API returns explicit provider errors and never falls back to mock adapters.

SEC caches include the provider in their key, preventing older mock facts from
being loaded as live financials. Existing historical sample/manual records are not
automatically deleted or relabeled. Re-fetch real companies and inspect their
provenance before using results.

## Scope

Live source retrieval is on demand, not streaming: prices are daily closes and
filings/trial milestones change on their own publication schedules. Clinical trial
dates do not imply successful outcomes and are not a complete FDA/PDUFA calendar.
DCF valuations and signals remain computed estimates; news sentiment is a labeled
keyword heuristic. Those outputs cannot become externally verified facts merely
by switching providers. No scheduled ingestion job is installed by this change.

Source references: [SEC data](https://data.sec.gov/),
[Twelve Data historical prices](https://support.twelvedata.com/en/articles/5214728-getting-historical-data),
[ClinicalTrials.gov API](https://clinicaltrials.gov/data-about-studies/learn-about-api),
[Financial Modeling Prep](https://financialmodelingprep.com/), [Finnhub](https://finnhub.io/).
