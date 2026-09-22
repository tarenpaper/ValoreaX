# Clinical phase-advancement NLP

The model's target is **whether a drug program advances from Phase 1 to Phase 2,
or from Phase 2 to Phase 3, for the same indication**. It estimates the chance
from language in a timestamped ClinicalTrials.gov study snapshot, alongside a
small set of study-design fields. It does not predict Phase 3 approval, meeting
a particular endpoint, or stock performance. A 70% score means a calibrated
estimated 70% chance of the specified next-phase transition in the reviewed
cohort; it is not a confidence interval or a guarantee.

No real transition-label dataset or trained model ships with the application.
Until an independently reviewed dataset is prepared, the page shows trial
coverage and withholds percentages.

## Data collection

From `backend/`, install `requirements-ml.txt`, then collect full registry
snapshots:

```sh
python -m pip install -r requirements-ml.txt
python -m app.ml ingest --query 'AREA[StudyType]INTERVENTIONAL' --limit 1000 --output ml-data/registry-snapshots.jsonl
```

On Windows, use `.venv\Scripts\python.exe` instead of `python` if the virtual
environment is not activated. The command creates a JSONL file and adjacent
`.manifest.json` showing the query, retrieval time, count, and whether results
were truncated. The same content version keeps its earliest observed retrieval
time on repeated pulls. `backend/ml-data/` is ignored by Git; copy it separately
between computers. Run one writer at a time per output path.

The broad example query is a coverage check, not a representative cohort. Define
the cohort before selecting labels. Collect both advancing and non-advancing
programs. The initial 100-record local smoke-check dataset is too small and too
recent to train this model.

Historical snapshots are essential. A current registry record cannot be
backdated to the study start date: it may include descriptions, amendments, and
posted results added years later. Use independently verifiable earlier versions
or prospectively captured files with their true availability time. AACT's archived
snapshots and ClinicalTrials.gov record histories are starting points, but the
current CLI does not import them automatically. Reconstructing historical v2-like
records with faithful provenance requires a separate importer and audit.

## What the NLP model reads

The feature extractor reads the following **as they appeared in the snapshot**:

- Registered brief and detailed descriptions; eligibility criteria; primary
  outcome names, descriptions, timeframes; and condition names.
- If posted before the prediction date, primary-result titles, descriptions,
  statistical comments, p-values, and measure values.
- Phase, design, estimated enrollment, arms, and whether results were posted.

It excludes trial IDs, registry status text, termination reasons, news,
company statements, and later-phase trial records from the language model.
A completed Phase 1 or 2 study can be scored if its snapshot predates the
next-phase transition and its protocol language is present. Current study
status is used only for eligibility. The word vectorizer learns its vocabulary
and inverse-document frequencies from the training partition only. Training
uses unigram/bigram TF-IDF plus design fields in a regularized logistic
regression, with separate sigmoid probability calibration.

## Reviewed transition labels

Put **one JSON object per line** in `ml-data/reviewed-transitions.jsonl`.
The following object is only a schema example, not a real trial outcome:

```json
{"nct_id":"NCT00000001","target":"next_phase_transition","outcome":1,"from_phase":"PHASE2","to_phase":"PHASE3","indication":"Example condition","drug_group":"curated-example-drug-family","prediction_at":"2020-02-01T00:00:00Z","outcome_at":"2021-03-01T00:00:00Z","known_at":"2021-03-02T00:00:00Z","reviewed_at":"2026-01-01T00:00:00Z","next_trial_nct":"NCT00000002","reviewer":"Named reviewer","source_url":"https://example.com/replace-with-evidence","rationale":"Replace with evidence that the same program advanced in the same indication."}
```

- `outcome: 1` requires a distinct, verified `next_trial_nct` in the specified
  next phase. Confirm the drug or biologic, aliases, sponsor transfer, and
  indication match. A Phase 1→2 and Phase 2→3 transition are the two supported
  events. A new trial for a different drug or indication is not a positive.
- `outcome: 0` requires `negative_reason` to be either
  `documented_discontinuation` or `reviewed_no_transition`. The latter needs
  at least three years of follow-up from `prediction_at` to `outcome_at`, a
  documented search, and expert review. A missing newer trial, `COMPLETED`,
  or `TERMINATED` status alone is **not** a negative label.
- `source_url` must point to the evidence; `rationale` should document the
  intervention and indication match or the negative decision. `drug_group`
  must unify aliases and combinations that could otherwise leak across splits.
- Require `prediction_at < outcome_at <= known_at <= reviewed_at <= as_of`.
  The source snapshot must have been retrieved no later than `prediction_at`
  and must describe the same `from_phase`. Choose one prediction landmark
  policy for the cohort, such as enrollment or shortly after the trial readout;
  do not choose dates after seeing which programs advanced.
- Program advancement can be delayed. Unresolved or poorly linked cases
  remain unlabeled. Do not use Kaggle completion status or a paper's mixed
  endpoint/approval label as a transition label without re-adjudication.

The training builder validates schema, chronology, snapshot hashes and phase.
It cannot verify scientific adjudication or whether an archived timestamp is
truthful. Review a sample independently before fitting a model.

## Fit and evaluate

Given genuine historical snapshots and reviewed labels, choose period boundaries
**before** examining held-out performance:

```sh
python -m app.ml train \
  --snapshots ml-data/historical-snapshots.jsonl \
  --labels ml-data/reviewed-transitions.jsonl \
  --train-until 2021-12-31T23:59:59Z \
  --calibrate-until 2023-12-31T23:59:59Z \
  --as-of 2026-09-01T00:00:00Z \
  --output ml-data/phase-transition-model.json
```

The dates are examples. The actual `as_of` cannot be in the future. At least
100 training, 40 calibration, and 40 test trials survive filtering, with at
least 10 examples of each class in each partition. These are minimum software
gates, not a sufficient dataset size. Training outcomes must be public by the
training cutoff; calibration outcomes must be public by the calibration cutoff.
Test predictions occur afterward. Drug families seen in an earlier partition
are removed from later partitions.

The JSON artifact reports Brier score, log loss, ROC-AUC, average precision,
calibration bins, phase breakdowns, exclusions, and comparisons with the overall
prevalence, phase-specific, **and design-only** baselines. A
`research_candidate` must improve Brier and log loss over all three baselines,
have test ROC-AUC at least 0.55, and a positive calibration slope. Otherwise it
is `evaluation_failed` and inference abstains. These heuristic gates do not
prove clinical utility or prospective accuracy. Reserve a new untouched cohort
for future model selection.

The artifact includes the fitted text vocabulary and IDF weights, design
scaling, coefficients, calibration, split membership and evaluation. Serving
uses plain JSON and standard-library math; it does not load a pickle or require
scikit-learn in the web backend.

## Score fresh trials and connect the app

```sh
python -m app.ml predict \
  --snapshots ml-data/fresh-snapshots.jsonl \
  --model ml-data/phase-transition-model.json \
  --output ml-data/phase-predictions.jsonl
```

A prediction includes a calibrated next-phase probability, the model and
snapshot IDs, the proportion of trial terms covered by the learned vocabulary,
and influential words and design features. Text features are associations,
not causal explanations. Inference abstains for an ineligible stage, unseen
design category, insufficient vocabulary overlap, failed or missing model,
known development/test trial, or snapshot at/before the model evaluation cutoff.

`evidence_reliability` is `moderate` only when the relevant phase has at least
40 held-out examples and vocabulary coverage is at least 50%; otherwise it is
`limited`. It is a coarse coverage indicator, not a second probability or a
confidence interval. There is no `high` designation without prospective work.

Configure the app backend with the deployed artifact path, then restart it:

```dotenv
CATALYST_PROVIDER=clinicaltrials
CLINICAL_ML_MAX_STUDIES=100
CLINICAL_ML_MODEL_PATH=/absolute/path/to/phase-transition-model.json
```

The Clinical Pipeline page can ingest an account-scoped sponsor cohort and show
trial estimates or abstention reasons. Sponsor matches and comparator drug names
must be verified. Several studies of one program are not combined into a
program-level score. No model output feeds the stock signal or valuation.

Primary references: [ClinicalTrials.gov study structure](https://clinicaltrials.gov/data-api/about-api/study-data-structure),
[ClinicalTrials.gov phase definitions](https://clinicaltrials.gov/study-basics),
[scikit-learn TF-IDF](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html),
and [AACT archived snapshots](https://aact.ctti-clinicaltrials.org/downloads/snapshots?type=flatfiles&year=2024).
