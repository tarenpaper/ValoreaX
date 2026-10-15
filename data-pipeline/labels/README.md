# Label adjudication protocol

The schema is enforced by `backend/app/ml/data.py::validate_label()` — the
builder rejects anything that doesn't conform, so this document is the
*human* protocol around it. Read `docs/CLINICAL_ML.md` ("Reviewed transition
labels") for the full rules; this is the operational checklist.

## Per-trial checklist

1. **Confirm the landmark.** The snapshot used for this trial must have
   `retrieved_at <= prediction_at` and describe the same `from_phase`.
   Choose the cohort's landmark policy once (e.g. primary-completion date),
   before looking at outcomes.
2. **Positive (`outcome: 1`).** Find the *distinct* next-phase trial:
   - same drug/biologic (check aliases; unify under one `drug_group`),
   - same indication,
   - sponsor continuity (note transfers explicitly),
   - record its NCT id as `next_trial_nct`.
3. **Negative (`outcome: 0`).** One of:
   - `documented_discontinuation` — cite the evidence, or
   - `reviewed_no_transition` — ≥3 years from `prediction_at` to `outcome_at`,
     a documented search, and expert review. A missing newer trial,
     `COMPLETED`, or `TERMINATED` status alone is **not** a label.
4. **Chronology.** `prediction_at < outcome_at <= known_at <= reviewed_at`.
   `known_at` is when the outcome became public; `reviewed_at` is when you
   adjudicated it.
5. **Evidence.** `source_url` points at the evidence (registry record, press
   release, filing); `rationale` explains the intervention/indication match or
   the negative decision in a sentence or two. Name the reviewer.

## Ambiguity policy

Unresolved or poorly linked cases **stay unlabeled**. Do not use Kaggle
completion status or a paper's mixed endpoint/approval label without
re-adjudication. The trainer reports exclusions; a growing exclusion count is
a signal to widen the cohort, not to relax the rules.

## File format

`data/reviewed-transitions.jsonl` — one JSON object per line, exactly the
schema in `docs/CLINICAL_ML.md`. An annotated example lives in
`reviewed-transitions.jsonl.example` (schema illustration only, not real data).
