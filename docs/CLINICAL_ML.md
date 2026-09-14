# Clinical trial success ML

The first implemented target is **trial-level primary-endpoint success**. This is a
research baseline, not a validated clinical predictor. No real trained model or
adjudicated outcome dataset is bundled. The Clinical Pipeline page exposes actual
coverage and leaves probabilities unavailable until a suitable model is configured.
Phase progression, regulatory approval, and commercial success require separate
labels and models. Do not multiply individual trial estimates into a program score:
trials within a drug family share biology, design choices, and evidence.

## Implemented workflow

1. Fetch full ClinicalTrials.gov v2 records, including studies without scheduled
   milestones. Paginate, retry transient errors, deduplicate NCT IDs, and disclose
   bounded/truncated pulls. Keep protocol and posted results intact for review.
2. Store timestamped, hashed snapshots. CLI reruns preserve the first retrieval
   time of each content version. App ingestion stores complete cohort pulls in
   `RawProviderResponse` under `clinical_ml_cohort`, scoped by owner and company identity, preserving
   history without a schema migration. Empty refreshes clear the latest view.
3. Join pre-prediction snapshots to independently reviewed outcome labels. Unknown,
   mixed, withdrawn, completed, or missing-results statuses are never binary labels.
4. Fit a standardized logistic regression using design features only. Fit sigmoid
   probability calibration on a separate, later cohort. Evaluate on a third cohort.
5. Save a versioned JSON model with coefficients, scaling, calibration, data hash,
   split membership, evaluation, exclusions, and limitations. Serving shares the
   feature extractor and loads no pickle or training dependencies.

## Capture a research dataset

From `backend/`:

```sh
.venv/bin/pip install -r requirements-ml.txt
.venv/bin/python -m app.ml ingest \
  --query 'AREA[StudyType]INTERVENTIONAL' \
  --limit 1000 \
  --output ml-data/registry-snapshots.jsonl
```

`CLINICALTRIALS_USER_AGENT` can identify your research project. Ingestion writes a
JSONL snapshot file and an adjacent `.manifest.json` with query, retrieval time,
count, and truncation status. `backend/ml-data/` is gitignored. Run one writer per
output path: writes are atomic but concurrent ingestion into the same file is not
supported. The manifest describes the latest pull; each snapshot retains its own
query and retrieval time. A broad capped query sorted by recent updates is a
**coverage sample**, not a representative training cohort. Define the cohort and
sampling policy before outcome curation, and retain failures as well as successes.

The initial live smoke check saved 100 interventional study records locally to
`backend/ml-data/registry-snapshots.jsonl`. This is a partial coverage sample, not a
training or validation result. It is separate from account-scoped app data.

Today's registry records cannot be used as historical features simply by changing
their timestamps to their study start or last-update dates. To train retrospectively,
use genuine previously captured snapshots with their original retrieval timestamps,
or build a separately audited archive import process that establishes historical
availability. Otherwise collect snapshots prospectively and wait for outcomes.
The current CLI deliberately offers no backdating option.

## Outcome adjudication contract

The label file is JSONL: one reviewed object per NCT ID. This illustrative object
shows the schema only; it is **not a real label**:

```json
{
  "nct_id": "NCT00000001",
  "target": "primary_endpoint_success",
  "outcome": 1,
  "drug_group": "curated-canonical-drug-family",
  "prediction_at": "2020-02-01T00:00:00Z",
  "outcome_at": "2021-03-01T00:00:00Z",
  "known_at": "2021-03-02T00:00:00Z",
  "reviewed_at": "2026-01-01T00:00:00Z",
  "reviewer": "Named reviewer",
  "source_url": "https://example.com/replace-with-primary-results-source",
  "rationale": "Replace with endpoint-specific evidence and decision rule."
}
```

- `1`: the prespecified primary-endpoint success rule was met, including required
  co-primary endpoints and multiplicity rules. `0`: an interpretable final analysis
  explicitly failed that rule. Record the rule, endpoint, analysis population,
  denominators, uncertainty, and supporting passage in the rationale.
- Keep ambiguous, mixed, administratively discontinued, or unreported outcomes
  **unlabeled**. A failed efficacy rule differs from an administrative termination.
  Do not derive labels from catalyst sentiment, news tone, LLM guesses, or status.
- `prediction_at` is the intended decision time; snapshot retrieval must be at or
  before it. `outcome_at` is the outcome event; `known_at` is when its supporting
  evidence became public; `reviewed_at` is actual adjudication time. Require
  `prediction_at < outcome_at <= known_at <= reviewed_at <= as_of`.
- `drug_group` is a curator-resolved family spanning aliases, sponsor transfers,
  and indications. Studies of overlapping combinations should share a connected
  family group. This value is used for split isolation, never as a predictor.
  String equality cannot discover aliasing; reviewers must resolve it beforehand.
- Use registry result tables, published trial reports, regulatory assessments or
  sponsor results disclosures with traceable evidence. Automated validation checks
  schema and timing, not the scientific correctness of adjudication. Independent
  review of the success rule and evidence is still required.
- Fix one prediction landmark policy (for example, phase entry) across the cohort;
  choosing dates after seeing outcomes introduces selection bias. Later human
  adjudication can reconstruct earlier public labels using `known_at`; evaluation
  is retrospective and does not imply the model existed at that time.

Snapshot records contain `schema_version`, `nct_id`, `retrieved_at`, `source`,
`source_url`, `query`, `content_hash` and the full `study`. `app.ml.data.snapshot`
constructs the format. Hash validation detects content changes; it cannot prove
that a manually supplied historical timestamp is truthful.

## Train and evaluate

Given genuine historical snapshots and reviewed labels:

```sh
.venv/bin/python -m app.ml train \
  --snapshots ml-data/historical-snapshots.jsonl \
  --labels ml-data/reviewed-outcomes.jsonl \
  --train-until 2021-12-31T23:59:59Z \
  --calibrate-until 2023-12-31T23:59:59Z \
  --as-of 2026-01-01T00:00:00Z \
  --output ml-data/endpoint-model.json
```

Dates above are examples; select them before examining held-out performance.
The builder rejects duplicate labels, conflicting versions with identical retrieval
times, altered hashes, future retrieval timestamps, unsupported targets, and invalid
label chronology. It reports exclusions for missing pre-prediction snapshots,
ineligible trials, labels unavailable by the evaluation date, outcomes unavailable
at fitting boundaries, and drug families crossing partitions.

Training labels must have become public by the training cutoff. Calibration trials
must have predictions after the training cutoff and outcomes public by the
calibration cutoff. Test trials must have predictions after calibration and labels
reviewed by `as_of`. Drug groups present in earlier partitions are purged from later
partitions. Never randomly split snapshots of the same trial or drug family.

The baseline requires at least 100 training, 40 calibration, and 40 test trials,
with at least 10 outcomes of each class in each partition. These are software floor
checks, **not sufficient statistical validation or a recommended dataset size**.
The report includes Brier score, log loss, ROC-AUC, average precision, calibration
bins, phase breakdowns, and comparisons against training-prevalence and smoothed
phase-specific baselines. Numeric feature scaling is fitted on training data only.

A `research_candidate` must improve both Brier score and log loss over both baselines,
have test ROC-AUC of at least 0.55, and positive calibration slope. Otherwise it is
saved as `evaluation_failed`, and inference abstains. These heuristic release gates
are intentionally modest and do not establish clinical utility. Add uncertainty
intervals, larger external cohorts, indication/mechanism subgroups, and prospective
validation before broader use. Repeatedly selecting models on this test set would
invalidate its role as an untouched holdout; use a new cohort for later comparisons.

The artifact contains split NCT IDs and drug groups for audit, but no label source
text or raw clinical data. Keep the source files and manifest with the model.

## Features and inference

Feature version `trial_design_v1` uses phase, allocation, intervention model,
masking, primary purpose, sponsor class, log planned enrollment and missingness,
arm count and missingness, primary-endpoint count, and drug/biological modalities.
Actual enrollment is excluded. Status, results, adverse events, termination reason,
trial dates, trial IDs, drug identities and free text are not model inputs.
Eligibility checks use status/results only to withhold already resolved trials.

```sh
.venv/bin/python -m app.ml predict \
  --snapshots ml-data/fresh-snapshots.jsonl \
  --model ml-data/endpoint-model.json \
  --output ml-data/predictions.jsonl
```

Inference covers active interventional phase 1–3 drug/biological trials with
registered primary endpoints and no posted results. It abstains for unsupported
phases, unseen categorical design values, trials included in development/evaluation,
snapshots at or before the evaluation cutoff, a failed model, or missing model.
It returns a snapshot hash/time, model ID, probability or abstention reasons, and
up to five signed feature contributions in calibrated log-odds. Contributions are
associations, not causal explanations or additive percentage points. Probability
is not a confidence interval. Numeric outliers and stale snapshots remain possible;
inspect provenance and refresh before use.

## App integration

Set the following backend environment variables and restart:

```dotenv
CATALYST_PROVIDER=clinicaltrials
CLINICAL_ML_MAX_STUDIES=100
CLINICAL_ML_MODEL_PATH=/absolute/path/to/endpoint-model.json
```

Leave the model path empty while building the dataset. The core backend needs no
scikit-learn at serving time. Install the optional ML dependencies on training/test
hosts. With serverless hosting, package the JSON artifact in the deployment and
point to a readable path; offline training does not run in API requests.

- `GET /api/v1/companies/<identifier>/clinical-ml`: latest evidence, model status,
  evaluation summary, per-trial estimates/abstentions, and limitations.
- `POST /api/v1/companies/<identifier>/clinical-ml/ingest`: fetch a bounded live
  sponsor cohort, save full snapshots, return the refreshed view. The existing
  authentication and company-owner checks apply to both routes.

The Clinical Pipeline page provides an **Ingest trial evidence** button. This full
snapshot workflow is separate from milestone-only catalyst ingestion. Gemini clinical
research reads the newest full cohort or legacy catalyst snapshot, and refreshes
after a successful full-evidence ingestion. It receives source evidence, not model
probabilities. Sponsor-name matches are approximate; intervention lists can include
comparators. Neither an NCT match nor a drug-name string verifies program ownership.
No new probabilities feed stock signals, valuation, or Gemini automatically.

## Next modeling work

1. Build an independently adjudicated drug–indication–phase dataset, with canonical
   intervention roles and drug-family identifiers, plus historical feature snapshots.
2. Extract endpoint effect sizes, comparator effects, uncertainty, safety signals,
   and prior-study evidence available before each prediction. Preserve full provenance
   and assess extraction quality before adding those features to training.
3. Add indication, mechanism, modality, sponsor track record and enrollment trajectory
   only after establishing time-aware joins; compare against this fixed baseline.
4. Train distinct phase-transition and approval models with explicit censoring,
   competing discontinuation reasons, and follow-up horizons. Validate drug-program
   aggregation against actual program outcomes rather than assuming independence.

Primary references: [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api),
[study data structure](https://clinicaltrials.gov/data-api/about-api/study-data-structure),
[registry glossary](https://clinicaltrials.gov/study-basics/glossary),
[scikit-learn logistic regression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html),
and [probability calibration](https://scikit-learn.org/stable/modules/calibration.html).
