# Signal verdict engine

A transparent LONG / SHORT / WATCHLIST score. Every input maps to a bounded, weighted
contribution with a plain-English explanation, so a reviewer can see exactly how each factor
moved the number. There is no model, hidden or otherwise — the verdict is a deterministic
function of the contributions and a data-completeness confidence.

Educational research output, not investment advice.

## Scoring

Contributions sum to a score in [-100, +100].

| Condition | Verdict |
| --- | --- |
| score ≥ +25 and confidence ≥ 35% | LONG |
| score ≤ −25 and confidence ≥ 35% | SHORT |
| otherwise | WATCHLIST |

The confidence floor comes first: a high score on thin data is a WATCHLIST, not a call.

## Components (engine `v4`)

| Component | Weight | Fed by |
| --- | --- | --- |
| `valuation` | 25 | price ÷ sum-of-the-parts value, vs a reference multiple |
| `catalyst_outcome` | 20 | the latest resolved catalyst, scaled for high-impact events |
| `exclusivity_runway` | 15 | revenue-weighted years to loss of exclusivity |
| `financial_health` | 15 | runway or FCF margin, plus dilution |
| `analyst_consensus` | 15 | the rating distribution, normalised to a tilt |
| `abnormal_return` | 5 | issuer return minus benchmark |
| `news_sentiment` | 5 | high-impact articles only |

A missing input produces **no component**, never a zero. `skipped` names each absent factor
and why, because a gap is not a neutral reading.

### Valuation is read *relatively*

This is the part that is easy to get wrong. The sum-of-the-parts rNPV
([VALUATION.md](VALUATION.md)) deliberately carries no terminal value, no platform value and no
value for pipeline it cannot support, so price ÷ SOTP sits **above 1× for nearly every
company** — Vertex ≈ 2.0×, Lilly ≈ 3.6× at the time of writing. An absolute threshold would
mark the entire market overvalued and short everything.

So the component scores the deviation from a reference multiple, and always names the
reference it used:

| `basis` | Reference | When |
| --- | --- | --- |
| `peer_median` | median price ÷ SOTP across the account's valued companies | ≥ 3 such companies |
| `own_range` | the company's own trailing median multiple, **carried at the benchmark** | fallback; needs ≥ 30 stored closes |
| `manual_upside` | none — an explicit upside was supplied | whenever the caller passes one |

40% below the reference is a full positive contribution. Peers are scoped to the account, so
another user's companies never enter the set.

#### Why `own_range` is benchmark-adjusted

Because SOTP is near-constant between 10-Ks, the value per share cancels out of the ratio:

```
multiple ÷ reference  =  (P_now / V) ÷ (median(P) / V)  =  P_now ÷ median(P)
```

So this basis is arithmetically *price against its own past*, which reads as **mean
reversion**. Left uncorrected it has no market control, while the momentum component
explicitly subtracts the benchmark — so a sector-wide rally would score as the company
becoming expensive at the same moment momentum reported *nothing company-specific*. One fact,
counted twice, in opposite directions.

Each historical close is therefore carried forward by the benchmark's move since that day:

```
P_adjusted(d)  =  P(d) × B_now ÷ B(d)
```

A company that merely tracked the market now shows a ratio of ~1.00 and scores neutral; one
that outran it still shows a rich multiple. Worked through:

| | unadjusted | carried at benchmark |
| --- | --- | --- |
| company +100%, benchmark +100% | −33% → bearish | **0% → neutral** |
| company +100%, benchmark flat | −33% → bearish | −33% → bearish |

Peer comparison needs no such correction — a market-wide move lifts the peer median too.
When no aligned benchmark history exists the raw median is used and the basis detail says
`no benchmark to adjust against`, rather than dropping the engine's largest component.

Against a genuinely company-specific move the two components still point opposite ways — that
is a deliberate blend of mean reversion at weight 25 and momentum at weight 5, not an
artifact.

### What no longer happens

Before `v4`, `valuation_upside` was auto-filled from the **analyst price target** while
`analyst_consensus` came from the same coverage — one opinion reaching the score twice, for an
effective 50 of 100 points, behind a UI label that read "Valuation (rNPV)". The auto-fill is
gone. Analyst coverage now drives `analyst_consensus` and nothing else.

### Exclusivity

```
weighted_years = Σ(rnpv_i × max(0, loe_i − start_year)) ÷ Σ rnpv_i
```

3 years or less is a full negative, 10 years or more a full positive. Risk-adjusted pipeline
value as a share of drug value offsets a cliff by up to 0.3 of a factor point — it never adds
to a company whose marketed drugs are already secure.

### Financial health

Stage-aware, averaging whichever figures the filings support ([DATA_SOURCES.md](DATA_SOURCES.md)):

- **runway** where the company is burning (under 4 quarters is a financing risk, over 8 a modest
  positive);
- **free cash flow margin** where it is not — a cash-generative company has no burn to divide by,
  so runway is `not_meaningful` and margin stands in;
- **dilution**, either way: share-count growth above 20% is a full negative, buybacks mildly
  positive.

### News

Only articles classified `critical` or `high` impact within 90 days, recency-weighted, and each
article scaled by its `sentiment_method` — a provider's own score counts fully, our keyword
heuristic at 0.6. The weight is 5 by design: news alone can never reach a directional verdict.
The classification is a labelled heuristic and the explanation says so.

## Confidence

`0.15 + 0.6 × completeness`, where completeness spans the seven directional inputs, plus a
proximity boost when a catalyst is near (≤30d +0.15, ≤90d +0.10, ≤180d +0.05).

Two things then scale it down:

- **Concentration.** Value concentrated in one drug above 60% reduces confidence, up to 20% at
  total concentration, with a warning naming the drug. Concentration never changes the
  *direction* — a focused company with a decade of exclusivity left is not bearish, only less
  certain.
- **A manual override**, when the caller supplies one.

## Versioning and the backtest

`ENGINE_VERSION` is stored on every persisted run. Weights and components differ between
versions, so `/signals/backtest` reports `by_engine_version` alongside the pooled headline rate
— a `v3` score and a `v4` score do not mean the same thing and are not comparable. The
evaluation itself stays look-ahead-safe: each run is scored against the first catalyst that
resolved *after* its `as_of_date` ([BACKTESTING.md](BACKTESTING.md)).

## Not used

Clinical-ML trial estimates. `docs/CLINICAL_ML.md` ships no trained model, predicts trial
endpoints rather than approval, and states plainly that no probabilities feed stock signals.
