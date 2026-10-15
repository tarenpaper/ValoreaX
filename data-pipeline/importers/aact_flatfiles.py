"""AACT monthly archive -> ValoreaX snapshot JSONL.

AACT publishes the whole ClinicalTrials.gov registry as pipe-delimited flat
files (one file per database table), as daily static copies and monthly
archives. This importer:

1. downloads an archive (or works from an already-extracted directory),
2. parses the pipe-delimited tables -- handling AACT's known quirk of
   unquoted text fields containing embedded newlines,
3. maps the relational tables onto the ClinicalTrials.gov v2-like study dict
   that `backend/app/ml/data.py::snapshot()` expects,
4. emits one JSONL row per eligible study, with `retrieved_at` set to the
   archive creation date (an explicit, auditable approximation -- never a
   backdate; see data-pipeline/README.md).

Only interventional drug/biological trials in standalone Phase 1 or Phase 2
are emitted by default; the trainer's `eligibility()` re-checks everything.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from .contract import load_contract

# Verify against the AACT data dictionary for the archive you use; column
# names are normalized to lowercase and a few aliases are tolerated.
_TABLES = {
    "studies": "studies.txt",
    "brief_summaries": "brief_summaries.txt",
    "detailed_descriptions": "detailed_descriptions.txt",
    "eligibilities": "eligibilities.txt",
    "design_outcomes": "design_outcomes.txt",
    "conditions": "conditions.txt",
    "interventions": "interventions.txt",
    "sponsors": "sponsors.txt",
    "designs": "designs.txt",
    "outcomes": "outcomes.txt",  # posted results, primary outcome measures
}

_PHASE_MAP = {
    "phase 1": ["PHASE1"],
    "phase 2": ["PHASE2"],
    "phase 1/phase 2": ["PHASE1", "PHASE2"],
    "phase 2/phase 3": ["PHASE2", "PHASE3"],
    "phase 3": ["PHASE3"],
    "phase 4": ["PHASE4"],
    "early phase 1": ["EARLY_PHASE1"],
}

_STATUS_MAP = {
    "not yet recruiting": "NOT_YET_RECRUITING",
    "recruiting": "RECRUITING",
    "enrolling by invitation": "ENROLLING_BY_INVITATION",
    "active, not recruiting": "ACTIVE_NOT_RECRUITING",
    "completed": "COMPLETED",
    "suspended": "SUSPENDED",
    "terminated": "TERMINATED",
    "withdrawn": "WITHDRAWN",
}


_NCT_ROW_START = re.compile(r"NCT\d{8}\|")


def iter_pipe_rows(path: Path):
    """Yield dict rows from a pipe-delimited file with embedded newlines.

    AACT text fields are unquoted and may contain newlines, so a physical line
    is not a logical row -- and a field-count heuristic fails when the broken
    field is the last column (the common case for descriptions). Instead we
    use AACT's structure: every table here is keyed by nct_id in the first
    column, so a physical line starting with ``NCT########|`` starts a new
    logical row and anything else continues the previous one.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        header = [h.strip().lower() for h in next(fh).rstrip("\r\n").split("|")]
        width = len(header)
        buffer = ""

        def flush():
            fields = buffer.rstrip("\r\n").split("|")
            if len(fields) != width:
                raise ValueError(
                    f"{path}: row has {len(fields)} fields, expected {width}; "
                    "embedded pipe characters break the format"
                )
            return dict(zip(header, [f.strip() for f in fields]))

        for line in fh:
            if _NCT_ROW_START.match(line) and buffer:
                yield flush()
                buffer = ""
            buffer += line
        if buffer.strip():
            yield flush()


def read_tables(tables_dir: Path, wanted: dict | None = None):
    """Read the needed *.txt files into {table: {nct_id: [rows]}}."""
    wanted = wanted or _TABLES
    grouped = {}
    for table, filename in wanted.items():
        path = tables_dir / filename
        if not path.exists():
            print(f"warning: {path} not found, skipping table '{table}'", file=sys.stderr)
            grouped[table] = {}
            continue
        by_nct = defaultdict(list)
        for row in iter_pipe_rows(path):
            nct = row.get("nct_id", "")
            if nct:
                by_nct[nct].append(row)
        grouped[table] = dict(by_nct)
        print(f"read {table}: {sum(len(v) for v in by_nct.values())} rows, "
              f"{len(by_nct)} studies", file=sys.stderr)
    return grouped


def _one(rows, key, default=""):
    return (rows[0].get(key, default) if rows else default) or default


def build_study(nct: str, tables: dict) -> dict:
    """Map AACT rows for one trial onto the v2-like study dict the contract reads."""
    get = lambda t: tables.get(t, {}).get(nct, [])
    study_row = get("studies")
    phases = _PHASE_MAP.get(_one(study_row, "phase").lower(), [])
    status = _STATUS_MAP.get(_one(study_row, "overall_status").lower(), "UNKNOWN")
    enrollment = _one(study_row, "enrollment")
    try:
        enrollment_count = int(float(enrollment)) if enrollment else None
    except ValueError:
        enrollment_count = None

    design_rows = get("designs")
    sponsor_rows = get("sponsors")
    lead = next((r for r in sponsor_rows if r.get("lead_or_collaborator", "").lower() == "lead"),
                sponsor_rows[0] if sponsor_rows else {})

    primary_outcomes = []
    for row in get("design_outcomes"):
        if row.get("outcome_type", "").lower() == "primary":
            primary_outcomes.append({
                "measure": row.get("measure", ""),
                "description": row.get("description", ""),
                "timeFrame": row.get("time_frame", ""),
            })

    interventions = []
    for row in get("interventions"):
        itype = row.get("intervention_type", "").upper().replace(" ", "_")
        interventions.append({"type": itype, "name": row.get("name", "")})

    posted = []
    for row in get("outcomes"):
        if row.get("outcome_type", "").lower() == "primary":
            posted.append({
                "type": "PRIMARY",
                "title": row.get("title", ""),
                "description": row.get("description", ""),
            })

    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct},
            "statusModule": {"overallStatus": status},
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": lead.get("name", ""),
                                "class": lead.get("agency_class", "") or "UNKNOWN"},
            },
            "descriptionModule": {
                "briefSummary": _one(get("brief_summaries"), "description"),
                "detailedDescription": _one(get("detailed_descriptions"), "description"),
            },
            "conditionsModule": {
                "conditions": [r.get("name", "") for r in get("conditions")
                               if r.get("name")][:10],
            },
            "designModule": {
                "studyType": (_one(study_row, "study_type") or "UNKNOWN").upper().replace(" ", "_"),
                "phases": phases,
                "enrollmentInfo": {
                    "count": enrollment_count,
                    "type": (_one(study_row, "enrollment_type") or "").upper().replace(" ", "_") or None,
                },
                "designInfo": {
                    "allocation": _one(design_rows, "allocation", "UNKNOWN") or "UNKNOWN",
                    "interventionModel": _one(design_rows, "intervention_model", "UNKNOWN") or "UNKNOWN",
                    "maskingInfo": {"masking": _one(design_rows, "masking", "UNKNOWN") or "UNKNOWN"},
                    "primaryPurpose": _one(design_rows, "primary_purpose", "UNKNOWN") or "UNKNOWN",
                },
            },
            "armsInterventionsModule": {"interventions": interventions, "armGroups": []},
            "outcomesModule": {"primaryOutcomes": primary_outcomes[:10]},
            "eligibilityModule": {"eligibilityCriteria": _one(get("eligibilities"), "criteria")},
        },
        "resultsSection": (
            {"outcomeMeasuresModule": {"outcomeMeasures": posted[:5]}} if posted else {}
        ),
    }


def build_snapshots(tables_dir: Path, as_of: str, query: str, output: Path,
                    phases=("PHASE1", "PHASE2"), limit: int = 0):
    contract = load_contract()
    contract.timestamp(as_of)  # fail fast on a bad timestamp
    tables = read_tables(tables_dir)
    ncts = sorted(tables.get("studies", {}))
    written, skipped = 0, 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as out:
        for i, nct in enumerate(ncts):
            if limit and written >= limit:
                break
            study = build_study(nct, tables)
            design = study["protocolSection"]["designModule"]
            study_type = design["studyType"]
            if study_type != "INTERVENTIONAL":
                skipped += 1
                continue
            if not (len(design["phases"]) == 1 and design["phases"][0] in phases):
                skipped += 1
                continue
            if not any(iv.get("type") in {"DRUG", "BIOLOGICAL"}
                       for iv in study["protocolSection"]["armsInterventionsModule"]["interventions"]):
                skipped += 1
                continue
            row = contract.snapshot(study, as_of, query=query)
            out.write(json.dumps(row, allow_nan=False) + "\n")
            written += 1
    manifest = {
        "retrieved_at": as_of,
        "query": query,
        "source": "aact-monthly-archive",
        "tables_dir": str(tables_dir),
        "studies_considered": len(ncts),
        "snapshots_written": written,
        "skipped_non_target": skipped,
        "note": ("retrieved_at is the archive creation date: an explicit, auditable "
                 "approximation of evidence availability, not a backdate."),
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    return manifest


def download_archive(url: str, dest: Path):
    import requests  # kept local so mapping/tests stay dependency-free

    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / "archive.zip"
    print(f"downloading {url} ...", file=sys.stderr)
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            fh.writelines(resp.iter_content(chunk_size=1 << 20))
    with zipfile.ZipFile(tmp) as zf:
        zf.extractall(dest)
    tmp.unlink()
    print(f"extracted to {dest}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="Download and extract an AACT archive zip")
    dl.add_argument("--url", required=True, help="Archive zip URL")
    dl.add_argument("--dest", required=True, help="Extraction directory")

    b = sub.add_parser("build", help="Map extracted tables to snapshot JSONL")
    b.add_argument("--tables-dir", required=True)
    b.add_argument("--as-of", required=True,
                   help="Archive creation date, ISO-8601 with timezone (retrieval time)")
    b.add_argument("--query", required=True, help="Provenance label, e.g. aact-monthly-2021-06")
    b.add_argument("--output", required=True)
    b.add_argument("--limit", type=int, default=0, help="Cap snapshots written (0 = no cap)")

    args = parser.parse_args(argv)
    if args.command == "download":
        download_archive(args.url, Path(args.dest))
    else:
        build_snapshots(Path(args.tables_dir), args.as_of, args.query,
                        Path(args.output), limit=args.limit)


if __name__ == "__main__":
    main()
