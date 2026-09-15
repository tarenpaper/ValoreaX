# Gemini dashboard research

Set GEMINI_API_KEY in backend/.env and restart the backend. GEMINI_MODEL defaults
to gemini-3.6-flash and can be changed to a supported Gemini text model. In Docker,
set the variables in the compose environment. Never use a VITE_ prefix for this key.

The dashboard automatically calls POST /api/v1/companies/<ticker>/research after
its data refresh. The authenticated endpoint checks ownership before looking up
cached results or generating research. Results are cached for five minutes by
account, company, model, prompt version and evidence hash. Changed evidence — including a
changed drug model — causes a new generation. No background polling or automatic
retries incur extra calls. The prompt version is a literal in the cache key
(`app/api/v1/research.py`); bump it whenever PROMPT or the response schema changes,
or clients keep receiving answers from the previous contract for up to five minutes.

Gemini receives a bounded snapshot of company profile, annual SEC metrics, twenty
daily closes, analyst consensus, and up to ten provider-sourced catalysts. Account
identifiers, email, credentials, investment amounts and manual catalyst notes are
excluded. It has no tools, browsing, or trading permissions. The UI shows the exact
evidence snapshot used; it may contain stale or sample data.

The snapshot also carries the platform's own deterministic outputs, as ordinary
cited evidence records:

- the latest signal run, expanded into its weighted components (name, input value,
  weight, contribution, explanation) rather than just its verdict and score, so the
  model has material to examine instead of a conclusion to restate;
- the sum-of-the-parts drug valuation, when the company has modelled drugs. The server
  recomputes it from stored data; the client sends no figures. Each drug reports its
  rNPV, probability of reaching market, exclusivity year, peak revenue and **share of
  total drug value**, alongside the programmes carried at no value and their reasons.
  Concentration is the point: a company whose value sits in one drug with a near-term
  patent cliff is fragile in a way the headline number hides, so the model is given the
  breakdown rather than the total.

The recommendation stays deterministic. The prompt instructs the model to treat both
as inputs to scrutinise and never to adopt their verdict, score or implied price as
its own recommendation. Disagreements surface in a separate `tensions` array, each
entry citing evidence like any driver or risk. An empty array means no conflict was
found. Validation applies the same limits as drivers and risks: at most four entries,
each citing at least one known evidence ID.

Responses are validated for structure and evidence IDs. Truncated, refused or
invalid responses are not cached as successful. References identify model inputs;
they are not proof that the interpretation is correct. Setup, quota and network
errors render in the panel without replacing the rest of the dashboard.

Failure modes report separately rather than collapsing into one message. Only the
HTTP call itself is wrapped in the transport handler; response inspection happens
outside it, so a safety block (`promptFeedback.blockReason` or a blocking
`finishReason`), an empty `candidates` array, a truncated answer (`MAX_TOKENS`) and
an unreadable body are each distinguishable from a genuine network failure. This
matters operationally: a blocked prompt needs a different response from a retry.

Uses Google's generateContent REST API and JSON Schema structured output:
https://ai.google.dev/gemini-api/docs/generate-content/structured-output

The Plutus question bar sends an optional question (up to 1,000 characters) to Gemini.
Questions are included in the cache hash; each distinct question has its own result.
This produces an evidence-based explanation, not an execution of model changes.

The dashboard re-runs the research only when the drug models actually change (an
override, an exclusion, a new filing), so the research panel and the valuation panel
describe the same model without spending a call on every re-render.

## Backtest explanation

POST /api/v1/companies/<ticker>/backtest accepts `explain: true` and an optional
`question`, and returns an `explanation` object beside the simulation figures.

This is deliberately **not** a predictive backtest. We never ask the model to make a
call at a historical point and then score it: an LLM's training data already contains
what happened to real tickers, so any resulting "accuracy" would measure leakage, not
skill. The period is finished and its outcome is supplied as evidence, so nothing is
being predicted.

The evidence is the simulation's own realised figures — result totals, the entry and
exit trend labels, a downsampled equity curve (at most 24 rows), the deepest drawdown
session, the detected inflection points, and the methodology with its exclusions. The
verdict versus the benchmark is computed in Python (`assess()`), not asked of the model.

### Two kinds of claim, kept apart

The response separates statements by how they can be checked:

- `summary`, `observations`, `cautions` and `tensions` describe the supplied figures.
  The three lists must each cite a known evidence ID; none of the four may rely on
  outside knowledge, and the prompt explicitly keeps recalled causes out of the summary.
- `context` explains *why* the detected inflection points moved. Every entry carries an
  `approximate_date` inside the simulated window and a `confidence` of high, medium or
  low, both enforced by `validate_backtest_result`, which rejects undated, mis-dated or
  ungraded entries rather than displaying them. Note that `confidence` grades the
  strength of the **causal link**, not whether the event occurred.

### Citing the news adapter

`news_windows` fetches headlines bracketing each detected inflection
(`NEWS_LOOKBACK_DAYS` before to `NEWS_LOOKAHEAD_DAYS` after, at most `NEWS_PER_POINT`
articles kept, closest to the move first) and adds them as `News around <date>` evidence
records. Historical news is immutable, so it caches for a week.

A context entry may then cite those records in `evidence_ids`. Validation permits only
news record IDs — citing a non-news record would dress a recollection as sourced — and
`sourced` is computed server-side from the citations rather than trusted from the model.
Where the provider has no coverage, `evidence_ids` stays empty and the entry renders as
unverified recollection. The UI shows **Sourced** entries with clickable headlines and
**Unverified** ones in a dashed box.

This requires a provider that can serve an arbitrary historical window, which the
`NewsProvider.supports_history` flag declares and `fetch_window` implements. Providers
without it return `[]`, and an empty window is reported to the model as a coverage gap —
explicitly *not* as evidence that nothing happened.

**Finnhub's free tier only covers roughly the last year.** Older backtests therefore get
no citable headlines and fall back to recollection. That is a provider limitation, not a
bug; a paid archive or a second adapter would extend it.

Citation proves the event was published near the move. It does not prove the event
*caused* it — headlines co-occur with price moves for many reasons, and the prompt
requires this caveat in `limitations`.

The inflection points are detected in Python by a zigzag filter over the equity curve
(`inflection_points`, swings above 12%), so the model explains dated moves that provably
happened instead of choosing which moves to narrate. That makes each recalled claim
falsifiable: a reader can check the named event against the dated move.

Note that look-ahead bias is not the concern here. It only applies when a prediction is
scored; this period is finished and its outcome is supplied, so recalled knowledge
biases nothing. The live risk is unverifiable attribution, which is what the labelling,
dating and confidence grading address.

Results are cached for five minutes per account, company, model, prompt version and
evidence hash, under its own `backtest:v3` version. The explanation never breaks the
simulation: a missing key returns `needs_setup` and a provider failure returns `error`,
both alongside the full numeric result.
