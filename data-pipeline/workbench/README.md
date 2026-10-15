# Labeling workbench (planned)

The adjudication in `labels/README.md` is manual today. The workbench makes it
fast without relaxing the rules. Planned shape:

## What it shows per candidate trial

- The landmark snapshot rendered readably: phase, status, brief/detailed
  description, eligibility, primary outcomes, conditions, interventions,
  enrollment — i.e. exactly the text the model will see.
- Side panel: the drug's other trials (same `drug_group` candidates), the
  sponsor's trial list, and any already-labeled relatives (to catch leakage
  before it happens).
- A verdict form: outcome 1/0/unresolved, `next_trial_nct` or
  `negative_reason`, evidence URL, rationale, reviewer name. Submitting runs
  `validate_label()` immediately and appends to
  `data/reviewed-transitions.jsonl` only on success.

## What it tracks

- Coverage dashboard: labels per phase, per drug-family, per outcome class,
  and exclusions — so you can see when the 100/40/40 gates are reachable and
  where the cohort is thin.
- Reviewer agreement: a second reviewer re-adjudicates a sample; disagreements
  stay unlabeled until resolved.

## Suggested implementation

Start as a small Streamlit or Flask app reading the local `data/` directory;
it needs no database. Keep it out of the main ValoreaX web app — adjudication
is a research operation, not a product surface, and mixing them risks leaking
labels into serving data.
