# Backend audit review

Reviewed October 15, 2026 against local commit `ef85c21` in `/Users/taran/Documents/ValoreaX-main`.
Source audit: `/Users/taran/Downloads/valoreax_backend_audit.md`.

## Implementation update — October 15, 2026

The high-priority database work from this review is now implemented locally:

| Tickets | Change | Verification |
| --- | --- | --- |
| A5 | One SQL statement counts the four child tables without materializing relationships. | One SELECT; correct counts and unloaded collections. |
| A4 | Dashboard financials and stage classification share the two-year metric load. | Two metric SELECTs for dated records; undated-only, empty, and non-consecutive-year cases retain their results. |
| A1 / E4 | A lazy, operation-local price snapshot feeds event attempts, trailing returns, and the own-range reference. | Two history SELECTs across those calculations; old event dates and the raw-price fallback remain available. New operations see changed prices. |
| A10 | Database window functions return seven prices and one latest signal per owned, watched company. | Timestamp takes precedence over ID; ID breaks timestamp ties. Signal JSON is not loaded. |
| E1 | SQL groups normalized sectors and repeated sentiment scores; exact weighted means retain Python rounding. | NULL, empty, and literal Unknown merge; owner isolation and half-thousandth rounding cases pass. Row reduction depends on repeated scores; arbitrary unique provider scores can still produce many groups. |
| E2 / E3 | News chart fetches only 40 prices; signal news is filtered by impact and the inclusive 90-day date window before loading. | Chart order and values retained; cutoff midnight and end-of-day boundaries pass. Date comparisons explicitly use UTC. |
| A9 / E5 | A sidebar refresh shares successfully committed benchmark work; news matrix and markers share catalysts. | One benchmark collection read per refresh, retry after failure, independent standalone sync, and one catalyst read per news view. |

Validation: **379 backend tests passed**, including **13 new regression cases** in `backend/tests/test_audit_optimizations.py`. These are offline SQLite/mock-provider checks, not production PostgreSQL performance measurements. No schema migration or frontend change is required.

The main news article stream still includes all stored articles, preserving its existing coverage; pagination remains a separate product change. Equal-time signals now use highest ID as an explicit tie-breaker, and equal-score sectors sort by name rather than unspecified database order. Medium/low-priority work such as WACC caching and SEC request reuse remains outside this implementation.

The assessment and tables below record the original review against `ef85c21`, before these implementation changes.

## Assessment

The audit identifies real repeated database reads, unnecessary object loading, and several small computation costs. It is useful as an optimization backlog, but its priority ordering and repeated claims of “zero behavior change” are not reliable enough to implement verbatim. No production outage, critical performance incident, or measured production bottleneck was established by this review. The audit uses P0 to mean a frequently used path; that should not be interpreted as a demonstrated emergency.

The highest-confidence work is to reuse data within a request, count records in SQL, restrict database results to what the caller actually uses, and avoid repeating an SEC submissions request during a filing rebuild. WACC caching is also worthwhile, but needs a complete freshness and invalidation design.

At the original review stage, no application code was changed and this document was the only repository addition. No live accounts, production database, or paid provider APIs were used in the investigation. Local checks used synthetic data in an isolated in-memory SQLite database and mock providers. PostgreSQL batching behavior was checked against official SQLAlchemy documentation, not measured on the production database.

## Evidence from isolated checks

| Check | Result | Interpretation |
| --- | --- | --- |
| A1: three resolved catalysts outside available price history, followed by trailing-return and own-range calculations | 10 price-history SELECTs, plus one catalyst SELECT | Repeated reads are real. This is a constructed worst-case scenario, not an estimate of normal production traffic. |
| A2: evaluate three companies | 7 SELECTs | Confirms `1 + 2N` query pattern. |
| A4: company summary with fiscal-year data | 5 SELECTs including company lookup | Latest metrics are queried once for headline values and again for the stage profile. |
| A5: serialize counts after loading the company | 4 collection SELECTs | Counts load filings, metrics, catalysts, and signal runs rather than aggregating in SQL. |
| A10: higher-ID run with an older timestamp | Current implementation returns `long`; suggested MAX(id) approach returns `short` | Proposed replacement changes behavior even without timestamp ties. |
| C1: 1,000 calls using the same regex term | 1 actual compilation | Python's regex cache contradicts the repeated-compilation claim. Repeated searches and lowercasing still occur. |
| C6: same valuation twice | WACC called twice; second valuation issued 8 SELECTs in the offline fixture | SOTP caching does not eliminate WACC preparation. This does not establish repeated HTTP requests. |
| C13: sort 500 items | 500 key-function calls | Key calculation is once per item, not O(n log n). |
| D1: resolve latest accession, then load the annual report | 2 submissions fetches through a stubbed HTTP layer | Duplication is real on the filing-rebuild path. |
| E1: sectors NULL, empty string, and literal `Unknown` | Existing code produces one group; proposed query produces three groups | Suggested SQL is not behavior-identical. |
| C5: 3,900-point synthetic curve, 100 repetitions | About 0.23 ms per inflection-point pass locally | Duplicate work exists, but this example does not justify a high priority. Not a production benchmark. |

Relevant existing backend tests: **58 passed**, covering market returns, evaluation, watchlist, news, WACC, normalization, and shared refresh. These tests are a baseline; they do not validate unimplemented fixes.

## Recommended work order

1. **A5 and A4 — cheap database-read reductions:** SQL counts and sharing the two-year financial-metric load. These are clear, contained improvements on ordinary company requests.
2. **A1, A9, E5 — reuse data within the request:** align prices once, update the shared benchmark once during a multi-company refresh, and fetch news-page catalysts once. Preserve endpoint behavior, failure handling, and ownership checks.
3. **A10, E1–E3 — reduce rows loaded as stored history grows:** latest signal by timestamp, the price rows actually displayed, and filtered news. Sector aggregation needs corrected grouping and rounding parity checks. The news page's main article load is also unbounded; changing its scope requires pagination or an explicit product decision.
4. **D1 and C8 — avoid duplicated network work and repeated fact scans:** pass the resolved filing through the same sync operation; index facts once by taxonomy/concept during normalization.
5. **C6 — cache WACC safely:** reuse its result only with complete input tracking or explicit freshness rules. Do not simply move the existing SOTP lookup ahead of WACC calculation.
6. **A2 and C9 — scale-dependent work:** batch evaluation for larger company/run counts; batch clinical-model validation if a model is configured. Neither is demonstrated to be a current production bottleneck.
7. **C1 and the smaller C/D findings — profile before prioritizing:** most are valid CPU or connection-management cleanups, but the audit does not establish their real share of response time.

## Finding-by-finding decisions

### A. Database query fan-out

| ID | Decision | What is legitimate / what needs correction |
| --- | --- | --- |
| A1 | Valid; proposed cutoff unsafe | `_aligned_closes` reloads issuer and benchmark histories for each attempted catalyst, the trailing fallback, and potentially the own-range valuation reference. Request-scoped reuse is appropriate. The claim that every caller needs at most 400 trailing days is false: event dates can be historical and the own-range median currently uses all available observations. A new cutoff can change results. Also, normal issuer ingestion replaces a configured recent window, 90 days by default; the issuer table does not normally accumulate unlimited history per company. The shared benchmark can grow. |
| A2 | Valid; priority depends on job use and scale | `evaluate_all` performs 1 + 2N queries and repeats catalyst filtering/sorting per run. Batch loading plus a stable sorted date index is sound. Very large batches should be chunked. The repository provides an evaluation CLI, but does not establish how frequently it runs in production. The CLI evaluates existing signals; it does not generate new runs. |
| A3 | Valid load inefficiency; low priority | All catalysts are loaded to choose the latest resolved and earliest upcoming event. Two targeted queries reduce rows but increase query count from one to two, so they can be slower for small collections over a remote database. A one-pass selection is another option. SQL needs explicit tie handling and matching treatment of empty outcomes and missing dates. |
| A4 | Valid | Summary performs two latest-metric queries and the profile performs another two-year load. Reuse `annual_metrics_by_year` and build the profile from that result. The suggested snippet alone is insufficient if `biotech_profile` is still called unchanged. Preserve the all-NULL fiscal-year case. |
| A5 | Valid; good early fix | Four lazy relationships are fully materialized merely to count them. Use SQL counts or a single statement with count subqueries. Current `len()` calls count every child, including signal JSON records. |
| A6 | Partially overstated | The first `_owned(ticker)` query is filtered to that ticker; it does not load the account's entire company list. Already-watched tickers return immediately without the second query. Sharing one full load can help the add/re-watch path, but can make the already-watched path heavier. |
| A7 | Valid, small | A fresh-session drug lookup can perform three queries; catalyst lookup performs two. A join can reduce them. Preserve the existing ownership boundary and intentional error behavior rather than scattering new authorization logic across handlers. |
| A8 | Valid, small | Research evidence loads all non-manual catalysts through the relationship before selecting ten. A filtered, ordered, limited SQL query is appropriate; specify a deterministic tie policy. |
| A9 | Valid database work; not repeated provider calls in the normal cached case | Every watched company calls benchmark upsert, loading and comparing the shared series again. But benchmark provider data already shares a five-minute cache, so this is primarily repeated SQL/parsing/comparison work. Hoisting must retain per-company error handling and standalone price-sync behavior. |
| A10 | Valid; MAX(id) fix incorrect | Watchlist loads all stored prices and every signal run although it only displays seven sparkline closes and the latest signal. Signal history can grow. Use per-company ranking ordered by `created_at DESC`, with an explicit tie-breaker. MAX(id) is not equivalent to newest timestamp; a counterexample was reproduced. Prices normally cover the configured recent window, so their growth risk is smaller than implied. |

References: [price alignment and callers](../backend/app/services/derivations.py), [evaluation](../backend/app/services/evaluation.py), [company summary](../backend/app/api/v1/companies.py), [count serialization](../backend/app/api/serializers.py), [watchlist aggregation](../backend/app/services/watchlist.py), [price synchronization](../backend/app/api/v1/prices.py).

### B. Bulk writes

| ID | Decision | What is legitimate / what needs correction |
| --- | --- | --- |
| B1 | Production round-trip claim unproven; volume claim incorrect | `session.add()` queues ORM objects; it does not immediately issue one INSERT. SQLAlchemy 2 supports batching ordinary ORM flushes on PostgreSQL, including psycopg. Actual statement counts depend on dialect and statement shape. Moreover, default normalization produces at most **72 metric rows and four filing rows**, not thousands. Identical cached facts can bypass persistence entirely. Bulk mappings may reduce object-management overhead, but are not a justified top priority without measurement. |
| B2 | Potential small optimization; same unsupported premise | Analyst ratings are queued then flushed. Default FMP coverage includes at most ten rating rows. Measure production SQL before claiming one network round trip per rating. |
| B3 | Potential small optimization; same unsupported premise | News insertion is capped per fetch, 40 by default, and deduplicates before insertion. Batching may reduce ORM overhead; the claimed round-trip count is not established. Preserve intra-batch deduplication. |

The official [SQLAlchemy 2 batching documentation](https://docs.sqlalchemy.org/en/20/changelog/whatsnew_20.html#optimized-orm-bulk-insert-now-implemented-for-all-backends-other-than-mysql) explicitly includes ordinary `Session.add()`/`add_all()` flushes. Production tracing is still needed to quantify this application's behavior. Source: [persistence](../backend/app/services/ingestion_service.py) and [normalizer](../backend/app/services/normalization.py).

### C. Computation

| ID | Decision | What is legitimate / what needs correction |
| --- | --- | --- |
| C1 | Real repeated work; explanation and P0 ranking overstated | Text is lowercased repeatedly and each term is searched separately. But Python caches recently compiled patterns: the isolated 1,000-call check compiled once. Combining terms may help, and lowercasing once is sensible, but alternation still has matching costs. No evidence supports “dominates news-view build.” Matching processes all programs and stored articles before limiting displayed matrix rows; output limits are not work limits. |
| C2 | Valid, modest | Fresh data is serialized then deserialized in three ingestion services. Retaining fetched dataclasses avoids reconstruction/date parsing. Serialization remains necessary for both cache storage and raw-response provenance, not only the cache. Verify fresh/cache parity and normalization of optional fields. |
| C3 | Redundancy real; proposed fix ineffective as written | All three helpers still call `.lower()` internally. Lowercasing the input before passing it to unchanged helpers adds another call. Removing the repeated work requires lowercased-input helper variants or shared analysis. |
| C4 | Valid, small | Tags JSON is decoded by the article serializer and topic counter. Share parsing only if the existing malformed-value behavior is preserved. |
| C5 | Valid, low priority | Inflection detection runs twice during configured explanation requests. Sharing the result is straightforward. One pass over a 3,900-point synthetic curve took about 0.23 ms locally; HTTP/LLM/database costs were not included. |
| C6 | Valid preparation cost; proposed cache key incomplete | WACC runs before the SOTP lookup and is called again on a hit. Its result is not simply discarded: it sets the automatic discount rate, participates in the SOTP key, and is returned as provenance. Price and Treasury fetches already have their own caches. A cache keyed only by company, latest quote, metrics values, and day misses historical-price corrections, benchmark changes, refreshed Treasury/fallback state, provider changes, and metric status. Use complete dependency tracking or an explicit acceptable TTL. |
| C7 | Valid, small | Repeated alias-set construction occurs in asset/product matching. Precomputation can preserve first-match ordering and avoid work. |
| C8 | Valid | Normalization scans the fact list for each candidate, currently 42 candidates. An index by taxonomy/concept avoids repeated scans while retaining row order and selection rules. This runs during actual normalization, not every unchanged cached ingest. |
| C9 | Valid when a model is configured; retain validation boundaries | The artifact is read/validated per view, revalidated per prediction, and its development/evaluation NCT set is rebuilt for every trial. Validate once per trusted batch and prepare that set once. Do not remove validation from the public `predict(row, artifact)` contract without replacing it with a trusted validated-model interface. An mtime cache also needs file-change handling and protection against mutation of shared cached dictionaries. The default model path is empty; no live model configuration was verified. |
| C10 | Valid, tiny | The window builder repeatedly sums buffered sentence lengths. A running length preserves the current threshold semantics. Small bounded windows limit the impact. |
| C11 | Valid, small | Evidence chunks are normalized repeatedly for item validation. Pre-normalizing is useful only if the helper also stops normalizing the already-normalized chunks. |
| C12 | Valid, small | Non-truncated trial evidence is JSON-serialized twice for budgeting. Reuse the string, recomputing only if the record is replaced. |
| C13 | Incorrect complexity claim | Python computes a sort key once per input item. The current date parse already occurs once per article per sort. Hoisting the pivot's ordinal is a tiny optimization; precomputing every article ordinal does not eliminate O(n log n) date parses because those parses do not exist. |
| C14 | Valid, tiny | Cached WACC dates are parsed for filtering, then again for included dictionary keys. Parse once. |
| C15 | Valid, tiny; numeric parity matters | `line.latest()` is called twice in the sort key. Avoiding that is straightforward. Reducing WACC mean/variance/covariance passes has little benefit on at most 253 intervals, and a different algebraic formula can alter floating-point stability. |

References: [news matching](../backend/app/services/news_analysis.py), [news assembly](../backend/app/services/news_service.py), [WACC](../backend/app/services/wacc.py), [valuation cache ordering](../backend/app/services/rnpv_valuation.py), [ML prediction](../backend/app/ml/prediction.py). Python documents both [regex caching](https://docs.python.org/3/library/re.html#re.compile) and [one key calculation per sort item](https://docs.python.org/3/howto/sorting.html#key-functions).

### D. Provider/network work

| ID | Decision | What is legitimate / what needs correction |
| --- | --- | --- |
| D1 | Valid on rebuilds; indefinite memoization unsafe | Resolving the accession and fetching a report each fetch submissions. Unchanged-filing syncs return before the second call. Pass the resolved filing into the same sync operation. App-lifetime memoization without expiry would prevent a warm instance from discovering newly published annual reports. |
| D2 | Connection reuse worthwhile; executor change needs care | FMP makes bare `requests.get` calls and constructs a small executor per fetch. Persistent connections may save handshakes. A global executor changes cross-request queuing, lifecycle, and concurrency behavior; a shared mutable Session also needs a concurrency design. This is not automatically an identical-behavior change. |
| D3 | Valid, small | SEC uses bare HTTP calls. Connection pooling can help, with care for the existing parallel filing downloads and provider instance lifetime. |
| D4 | Valid over-fetch; proposed range needs boundary tests | Requesting twice the number of calendar days as observations over-fetches daily trading data. The exact fraction discarded is not established. Date-bounded retrieval is worth considering, but must preserve the final session and price-adjustment behavior; `get_history` deliberately requests the next day as its end boundary. This changes payload size, not necessarily request count or provider credits. |
| D5 | Observed truncation, not an established avoidable defect | The adapter downloads a window then keeps up to 40 articles. The audit itself identifies an API limitation. Narrowing the window changes coverage. No independent current Finnhub endpoint/plan verification was performed in this review. |
| D6 | Valid caching trade-off | Profile refresh fetches SEC submissions even when facts are cached. A TTL can save traffic but introduces staleness; choose that policy explicitly. |

References: [SEC provider](../backend/app/providers/sec_edgar.py), [drug sync](../backend/app/services/drug_sync.py), [FMP](../backend/app/providers/fmp_analyst.py), [Twelve Data](../backend/app/providers/twelve_data.py).

### E. Unnecessary data loading

| ID | Decision | What is legitimate / what needs correction |
| --- | --- | --- |
| E1 | Valid; proposed SQL grouping is wrong | Sector sentiment reads every relevant sentiment score into Python. SQL aggregation can reduce transferred data, but `sector or 'Unknown'` combines NULL, empty string, and literal `Unknown`. The suggested `GROUP BY Company.sector` plus `coalesce` does not. Group by the normalized expression and check rounding/tie order. |
| E2 | Valid; duplicate-date caveat unnecessary under this schema | The chart loads every stored issuer price to return 40. Select date/close and limit in SQL, then reverse. The model already has a unique `(company_id, date)` constraint, so duplicate-date ordering is not an ordinary concern. Normal issuer price history is bounded by refresh policy, making this a modest optimization. |
| E3 | Valid; timestamp semantics need care | Signal derivation loads all company articles and keeps high/critical articles within 90 days. Push filtering into SQL. Explicit timestamp ranges are generally preferable to applying a date function to an indexed timestamp. Match the intended timezone and inclusive end day on PostgreSQL and SQLite. |
| E4 | Duplicate of A1 | Do not count this as an additional independent issue. |
| E5 | Valid, small | Catalyst matrix and chart markers fetch the same company catalysts separately. Share the request-local list. |

## Interpretation of the “already efficient” section

Most listed protections exist: batched watchlist reads, existing-record lookup dictionaries, provider caches, valuation projection caching, and shared own-company valuation. They do not prove overall performance. Two clarifications matter:

- “Top ten catalysts” limits the research payload, not the relationship query; A8 correctly identifies the load before slicing.
- The backtest already passes at most 60 price points to per-session `trend_at`, while preserving all known stock observations when assembling those windows. The audit's description of passing the full history per row does not match the current implementation.

The next useful production measurement is endpoint timing plus SQL count/rows returned, especially for dashboard, watchlist refresh, news, and repeated valuation requests. That would establish whether the confirmed inefficiencies are material at the current account sizes rather than ranking them from loop shapes alone.
