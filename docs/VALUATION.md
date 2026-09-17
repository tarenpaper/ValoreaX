# Valuation — sum-of-the-parts rNPV

A biotech's value sits in a handful of discrete drugs, each with a launch ramp, a peak, and a
cliff when exclusivity ends. A single company growth rate and a perpetual terminal value
describe none of that, so this platform values **each drug as its own mini-company** — a
risk-adjusted NPV — and aggregates the drugs into one company value.

**There is no terminal value.** A drug's revenue ends when its patents do.

Everything is built automatically from the company's own SEC filings. Nothing needs entering,
and every value can be overridden or a drug excluded.

## Where each number comes from

Every input carries one of five provenance labels, shown in the UI and returned by the API:

| Label        | Meaning                                                  |
| ------------ | -------------------------------------------------------- |
| `sec`        | Reported in the filing's XBRL.                            |
| `sec_quoted` | Quoted verbatim from the filing's text, quote verified.   |
| `derived`    | Computed from the company's own reported figures.         |
| `benchmark`  | A published industry figure (`rnpv_benchmarks.py`).        |
| `override`   | The user's edit.                                          |

### Per-drug revenue — `services/product_revenue.py`

Company-facts (the API behind every other metric) has no product detail, so revenue per drug
comes from the 10-K's **XBRL instance document**, on `srt:ProductOrServiceAxis`. The parser
handles what real filings actually do:

- both revenue tags (`RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`);
- a worldwide figure from a product-only context, or the sum of a geography partition when the
  filer only reports US / non-US; the basis travels with the value;
- products reported inside a segment or reporting unit (Pfizer) as well as standalone (Vertex);
- **no double counting** — a therapeutic-area parent that contains its own products (Lilly's
  Cardiometabolic Health contains Mounjaro) is dropped, using the definition linkbase's
  domain-member arcs;
- classification of each line as `product`, `royalty_collaboration`, `aggregate` or `other`,
  with a stated reason. Aggregates ("Product revenues, net", "Excluding Comirnaty and Paxlovid")
  and the registrant's own subsidiaries are not drugs.

### Pipeline, populations and exclusivity — `services/llm_filing.py`

These exist only in the 10-K's prose, so Plutus (Gemini) extracts them under a strict contract.
A deterministic locator cuts the relevant section, splits it into cited chunks, and bounds the
size; two calls per filing are made, cached per accession — roughly once a year per company.

Every extracted item must carry a **verbatim quote**, and the validator drops anything that
fails rather than repairing it:

- the quote must appear in the cited chunk, whitespace-normalized;
- the numbers, names and phase text must appear inside the quote;
- enums must hold (phase, territory, geography).

Deterministic post-processing then runs in Python, not the model: the effective LOE per
territory is the **latest** protection listed (Mounjaro US 2036, not the 2027 data-protection
date); "Phase 2/3" maps to Phase 2, the conservative reading; a programme that is really a
marketed drug in the same indication is deduplicated away.

A patent table often names two brands at once ("Mounjaro/ Zepbound") where XBRL reports them
separately, so combined names are split before matching.

Three more naming hazards are handled so one molecule does not become several programmes:

- **FDA biologic suffixes.** Every biologic generic name carries a meaningless four-letter
  suffix, so Trodelvy appears as "Trodelvy" in the product table and
  "sacituzumab govitecan-hziy" in the pipeline. Alias lookup falls back to the unsuffixed
  form — exactly four letters, so three-letter stems like `exa-cel` are untouched.
- **The filing's own shorthand.** Gilead introduces "sacituzumab govitecan-hziy" and later
  writes "SG", which would otherwise become a programme of its own. A name of four
  characters or fewer that is an initialism or prefix of exactly one other programme is
  expanded to it; an ambiguous abbreviation is left alone rather than guessed at.
- **Combinations are not shorthand.** "dom and zim" (domvanalimab + zimberelimab) is a real
  programme distinct from either component, so it is deliberately left as it is.

The same molecule in a *different indication* remains a separate asset — Trodelvy is in four
Phase 3 indications at Gilead, and those are four programmes, not one duplicated.

Without a Gemini key, marketed drugs are still modelled from XBRL; the pipeline and exclusivity
dates are reported as unavailable rather than guessed.

### Peak sales for pipeline drugs — `services/drug_assets.py`

SEC never states peak sales, so they are derived:

> disclosed patient population × what the company already earns per patient

The **analog rate** is the latest-year revenue of the company's *established* indications
(three years of reported sales) divided by their disclosed populations, pooled. Revenue is
grouped by indication first, so one population serving two drugs is counted once. A US
population is compared with US revenue where the filing allows; a mismatch is flagged.

Four guards keep this honest:

- **Already-served indications are not valued.** A next-generation drug for an indication the
  company already sells into would re-count patients whose revenue the marketed drug's model
  already carries. It is listed with that reason and no value.
- **Overstatement flag.** A derived peak above the company's largest current product is capped
  at it, and both the cap and the uncapped figure are shown with a warning.
- **No population, no value.** A programme without a disclosed population is listed with its
  phase, probability and timing, and no number.
- **No analog, no value.** A company with no established indication — most pre-revenue
  companies — values no pipeline at all.

### Benchmarks — `services/rnpv_benchmarks.py`

The only inputs from outside the filings, collected in one module, labelled, and overridable:

- cumulative probability of reaching market by phase, from BIO / Informa / QLS *Clinical
  Development Success Rates 2011–2020* (≈ 7.9% / 15.1% / 52.4% / 90.6%). **Verify against the
  published report before relying on these commercially**; rates vary widely by therapeutic
  area, which this does not model. Preclinical programmes have no published rate here and are
  deliberately left unvalued.
- years to launch and to peak — planning conventions.
- exclusivity for a pipeline drug the filing gives no expiry for: assumed to run 12 years from
  launch. Without it a programme would plateau to the end of the horizon, which is the
  perpetual-value assumption this model exists to avoid.
- post-exclusivity erosion, small molecule vs biologic. SEC cannot tell modality, so the small
  molecule (faster erosion, lower value) is the default.

## The engine — `services/rnpv.py`

Pure, no I/O. Per drug, yearly to a 25-year cap:

- **Revenue** — marketed drugs start from the latest SEC product revenue and grow at their own
  trailing rate (capped), decaying to flat; pipeline drugs ramp from launch to derived peak.
  Both then plateau to LOE and erode.
- **Probability** — 1.0 for marketed and royalty lines; the phase's cumulative probability for
  pipeline programmes.
- **Costs** — cost of goods from the company's SEC gross margin, commercial cost from its SG&A
  share of revenue. Royalty lines carry neither: they arrive net.
- **Development cost** — the published annual cost of running a programme at its phase, per
  programme. It is deliberately *not* the company's R&D budget divided by the programmes its
  10-K happens to name: Lilly's $13.3B funds hundreds of programmes, so splitting it across
  the nine named in Item 1 charged each $1.48B a year and drove their value negative. R&D
  beyond the modelled programmes is not subtracted, because the model also omits the future
  programmes that spending will create — the same symmetry that keeps terminal value out.
- **Risk weighting** — revenue is uncertain, the spending to get there is not:

  ```
  risked = (cash_flow + development) × probability − development
  ```

- **Tax** — the company's SEC effective rate (income tax ÷ pretax income, bounded 0–35%), or
  21% statutory when pretax income is negative. Applied to positive flows only; NOLs are not
  modelled.
- **Discounting** — default 10%, editable. Clinical risk sits in the probabilities, so the rate
  must **not** also carry a risk premium.

### Continuing value — the pipeline the filings cannot support

Most large pharma discloses no patient populations at all. Lilly's 10-K contains none: every
"approximately N people" in it is an employee count, and the only population-shaped figure is
the Orphan Drug Act's own 200,000 threshold. Across seven companies checked, only Vertex (8)
and Moderna (4) disclose any; Lilly, Gilead, Biogen, Amgen and Regeneron disclose none.

Recording those programmes as worth nothing understates those companies systematically. So a
**continuing value** stands in, on the company's own **median established marketed product**,
halved. The median rather than the mean keeps one blockbuster from setting the bar; the
three-year established rule keeps a just-launched drug out (Vertex's median across all four
products is $0.5B, because Casgevy and Journavx have barely started selling — established-only
gives $5.6B); and the haircut reflects that this analog is weaker than a disclosed population.

It is still not a terminal value. Each programme is a finite drug model, risk-weighted by
phase and ending at a patent cliff. It sits on **its own waterfall line** so drug value stays
the number the filings support, and it can be switched off with
`include_continuing_value: false`.

Two exclusions matter:

- Programmes withheld for **cannibalisation** or for having **no published success rate** get
  nothing. Those are real absences of value, not undisclosed ones.
- A programme worth **less than it costs to finish** is treated as discontinued rather than
  counted against the company — management can stop funding it, so its downside is bounded at
  zero. For a company whose median product is small this is common: half of a $565M median
  cannot cover a $300M-a-year Phase 3.

### Aggregation

```
Σ valued drug rNPV + continuing value − PV of corporate overhead + net cash
    = equity value ÷ shares
```

Overhead is SG&A not already charged to a marketed drug, discounted only over the life of the
drugs being valued — never in perpetuity. R&D is not subtracted again at the company level:
each programme carries its own, and an unvalued programme's cost is excluded along with its
value, so a company whose pipeline cannot be valued is not worth less than its cash.

With no valued drug the result is **"no company value shown"** next to net cash, not a number.

## Storage

Migration `0004`:

- `product_revenues` — one row per XBRL member and fiscal year, with accession, tag and
  geography basis. Unique on company + member + year.
- `drug_assets` — the modelled drug. `extracted` (what the filing said, with quotes) and
  `overrides` (your edits) are **separate JSON columns**, so a newer 10-K refreshes the filing's
  values without discarding your work.

Both are account-scoped through the company and carry row-level security on PostgreSQL.

## API

| Method | Path                            | Description                                            |
| ------ | ------------------------------- | ------------------------------------------------------ |
| GET    | `/companies/{id}/drugs`         | Drugs with extracted values, overrides, and product lines. |
| POST   | `/companies/{id}/drugs/sync`    | Rebuild from the latest 10-K. Skips until a new one appears; `{"force": true}` overrides. |
| PATCH  | `/drugs/{id}`                   | Set overrides, `included`, or `reset_overrides`.        |
| POST   | `/companies/{id}/valuation`     | Run the sum-of-the-parts rNPV.                          |

```json
{ "discount_rate": 0.10, "horizon_years": 25, "include_sensitivity": false }
```

Pass `"include_sensitivity": true` for the 5×5 discount × sales grid. It re-projects
every drug, so it is off by default.

The response carries the waterfall, each drug's yearly model and provenance, the unvalued
programmes with their reasons, excluded drugs, the economics and their sources, and
(when requested) a sensitivity grid over discount rate × a proportional shift in every
drug's sales (each cell is re-projected, since costs do not scale with revenue).

## What this does not model

Per-drug NOLs, litigation or settlements changing an LOE date, platform or replenishment value
beyond the modelled drugs, quarterly product revenue, market-implied pipeline value, and any
feedback from the valuation into the signal score.

Not investment advice. The benchmarks are published averages, the peak-sales analog is an
estimate, and neither is a filing fact.

## Lifecycle and scenario consistency

- Growth uses elapsed fiscal years, including gaps in the reported history.
- Post-expiry marketed sales are anchored to the reported fiscal year; only subsequent
  changes in the erosion curve are applied to already-eroded revenue.
- Explicit peak-sales/probability overrides re-evaluate an unvalued pipeline asset's
  eligibility. Resetting overrides restores the extracted-data limitations.
- Missing assets are retired from valuation after their source is successfully processed.
  They remain visible, retain overrides and inclusion preferences, and can be restored if
  they reappear. Failed pipeline extraction does not retire prior pipeline records.
- Company research accepts `discount_rate` (0.01–0.50, default 0.10). The dashboard sends
  its selected rate; the resulting evidence participates in the research cache key.

## Deployment

Apply migration `0004_drug_assets` with `alembic upgrade head` from `backend` against the
intended database before deploying this version. It adds product revenue and drug asset
storage and enables PostgreSQL row-level security. Existing companies build their drug
models on the next valuation sync. Deploy the matching frontend and backend together:
the valuation request/response replaces the previous company-wide DCF contract.
