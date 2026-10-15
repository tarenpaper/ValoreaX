# Clinical ML data pipeline

The model in `backend/app/ml/` is a complete training/serving pipeline with no
dataset. **This workspace builds that dataset**: historical registry snapshots,
reviewed transition labels, and the tooling to curate them.

## The contract (read this first)

Everything this workspace produces must satisfy the contract in
`backend/app/ml/data.py` — it is the single source of truth and is validated
strictly on both the training and serving paths:

- **Snapshot rows** come from `snapshot(study, retrieved_at, query=...)`: the
  `study` dict must look like a ClinicalTrials.gov v2 API record
  (`protocolSection` / `resultsSection`), carry a valid `NCT\d{8}` id, a
  timezone-aware `retrieved_at`, and a sha256 `content_hash` over the study
  payload. `retrieved_at` is *evidence availability* — it is never backdated
  to a registry event.
- **Labels** follow `validate_label()`: one JSON object per line, outcome as
  integer 0/1, positives need a distinct verified next-phase NCT id (same drug,
  same indication), negatives need `documented_discontinuation` or
  `reviewed_no_transition` with ≥3 years of follow-up, and the chronology
  `prediction_at < outcome_at <= known_at <= reviewed_at` must hold.
- The importer loads these modules **directly by file path** (see
  `importers/contract.py`) so the pipeline stays dependency-light — it must
  never import the Flask `app` package.

## Workflow

```
AACT monthly archive (pipe-delimited flat files)
        │  importers/aact_flatfiles.py
        ▼
data/snapshots-<archive-date>.jsonl        ← versioned, auditable, git-ignored
        │
        │  labels/ adjudication (workbench/)
        ▼
data/reviewed-transitions.jsonl
        │
        │  cd backend && python -m app.ml train ...
        ▼
phase-transition-model.json  →  CLINICAL_ML_MODEL_PATH
```

## The hard rule about history

A *current* ClinicalTrials.gov record cannot serve as a pre-event snapshot: it
may contain descriptions, amendments, and posted results added years after the
landmark. Therefore every snapshot in this workspace comes from a **monthly AACT
archive dated on or before the prediction landmark**. The archive's creation
date is recorded as `retrieved_at` and in the output manifest — an explicit,
auditable approximation, not a backdate. `importers/ctgov_history.py` documents
the alternative (ClinicalTrials.gov record histories) for per-trial version
reconstruction.

## Layout

| Path | Purpose |
| ---- | ------- |
| `importers/aact_flatfiles.py` | Download → parse → map AACT tables to v2-like study dicts → snapshot JSONL |
| `importers/contract.py` | Loads `backend/app/ml/data.py` by path, no Flask dependency |
| `importers/ctgov_history.py` | Design notes for the record-history importer (per-trial versions) |
| `labels/` | Adjudication protocol + `reviewed-transitions.jsonl` schema (points at `validate_label`) |
| `workbench/` | Plan for the labeling UI |
| `tests/` | Mapping/parser tests with small AACT fixtures |
| `data/` | Local, git-ignored: downloaded archives and emitted JSONL |

## Running it

```sh
cd data-pipeline
pip install -r requirements.txt

# 1. Download a monthly archive (see AACT_FLATFILE_URL in the importer)
python importers/aact_flatfiles.py download --url <archive-zip> --dest data/aact-2021-06

# 2. Map to snapshot rows; --as-of is the archive creation date (retrieval time)
python importers/aact_flatfiles.py build \
    --tables-dir data/aact-2021-06 \
    --as-of 2021-06-01T00:00:00Z \
    --query "aact-monthly-2021-06" \
    --output data/snapshots-2021-06.jsonl

# 3. Curate labels (labels/README.md), then train from backend/
cd ../backend
python -m app.ml train \
    --snapshots ../data-pipeline/data/snapshots-2021-06.jsonl \
    --labels ../data-pipeline/data/reviewed-transitions.jsonl \
    --train-until 2021-12-31T23:59:59Z \
    --calibrate-until 2023-12-31T23:59:59Z \
    --as-of 2026-09-01T00:00:00Z \
    --output ../data-pipeline/data/phase-transition-model.json
```

## Scale target

Minimum software gates: 100 train / 40 calibration / 40 test trials with ≥10
per class in each — after exclusions (drug-group purge, snapshot-before-landmark
rule, phase mismatch). Realistically this means reviewing several hundred
trials. Track coverage in the workbench before training.
