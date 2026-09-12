# Historical investment simulation

Select a company, open Backtest, enter a start date, end date, and initial USD
investment, then choose **Run simulation**. The new view replaces the catalyst
agreement scaffold with a buy-and-hold simulation. The older signal evaluation
endpoint and administrator job remain available separately.

## Inputs and data

`POST /api/v1/companies/<identifier>/backtest` accepts:

```json
{"start_date":"2020-01-01","end_date":"2021-12-31","investment":10000}
```

An authenticated account must own the company. The date range must be no more than
15 years, start in 1900 or later, and end before today in New York. Investment must
be finite and between $1 and $1 billion. Daily data availability depends on listing
history and the provider subscription.

Twelve Data supplies explicit date-bounded daily history with `adjust=splits`.
The adapter requests one extra end day and filters back to the inclusive requested
boundary. Up to 120 prior calendar days supply the 60-session trend warmup. Only
USD instruments are accepted. Prices and benchmarks are cached for five minutes under
date-, symbol-, provider-, and adjustment-specific keys. Portfolio results and
amounts are not written into the shared cache. Existing recent-price tables and
research signals are not overwritten.

## Accounting

- Enter at the first shared stock/benchmark close on or after the start date.
- Exit at the last shared close on or before the end date; show both actual dates.
- Invest the whole amount using fractional split-adjusted units and hold them.
- Daily portfolio value = initial amount × daily adjusted close / entry adjusted close.
- Compare with the same amount invested in XLV (or the configured benchmark) over
  exactly the same sessions.
- Drawdown = value / highest previous value − 1. Maximum drawdown is the lowest value.
- Annualized return uses actual calendar days and is shown only for holdings of at
  least 365 days. Excess return is a percentage-point difference, not risk-adjusted alpha.

These are price-only returns. Dividends, commissions, slippage, taxes, cash interest,
and non-split corporate-action distributions are excluded. Adjusted price units are
not a reconstruction of the exact historical share count. This is a hypothetical
single-stock investment, not a strategy trading backtest.

## Historical outlook

Each displayed daily trend uses only closes through that session. The entry
assessment stops at the preceding available close, before investment. Positive:
close > 20-session simple moving average > 60-session simple moving average.
Negative: the reverse. Otherwise mixed. Fewer than 60 earlier observations yields
"Insufficient history".

This describes historical price trends. It does not reconstruct historical analyst
recommendations or use today's SEC metrics, catalysts, or news. It does not forecast
future returns. The chart slider and daily records show the trend through the period.

## Data quality and validation

Missing stock/benchmark matches are omitted with a warning; no prices are filled
or interpolated. Fewer than two shared sessions, boundary coverage gaps beyond
seven calendar days, internal gaps beyond seven days, conflicting/invalid prices,
and provider truncation are rejected. Small boundary shifts such as weekends and
holidays are disclosed. Returned retrieval timestamps distinguish cached records.

Tests cover dollar accounting, fractional investment, benchmark comparison,
drawdown, annualization, date boundaries, exclusion of future prices from the trend,
provider parameters, input validation, account isolation, and cache reuse across
different investment amounts. A live PFE/XLV 2020–2021 retrieval was also exercised.

Reference: [Twelve Data historical requests](https://support.twelvedata.com/en/articles/5214728-getting-historical-data)
and [price adjustment](https://support.twelvedata.com/en/articles/5179064-are-the-prices-adjusted).
