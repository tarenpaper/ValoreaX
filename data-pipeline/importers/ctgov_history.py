"""Design notes: ClinicalTrials.gov record-history importer (not yet implemented).

The AACT monthly archives give one full-registry picture per month. For finer
per-trial version history, ClinicalTrials.gov exposes each study's version
history (the "History of Changes" on a study page). A record-history importer
would:

1. For each NCT id in the cohort, fetch the version list and each version's
   full v2 JSON (`https://clinicaltrials.gov/api/v2/studies/<nct>` at the
   version's date).
2. Emit one snapshot row per version with `retrieved_at` = the version's
   submission/posting date (still an approximation of true availability, but
   per-trial rather than per-archive).
3. Write a manifest mapping (nct_id, version_date) -> archive/version source
   so every row's provenance is auditable.

Open questions before building it:
- The v2 API's version-history endpoints are less documented than the current-
  record endpoints; verify the exact routes and rate limits first.
- Decide the version-selection policy: earliest version on/after the landmark?
  latest version on/before it? (The trainer takes the latest snapshot with
  `retrieved_at <= prediction_at`, so the importer just needs to emit all
  versions faithfully.)
- Cross-check a sample of history-derived snapshots against the same month's
  AACT archive to catch mapping drift.

Until this exists, the AACT archive importer is the supported path.
"""
