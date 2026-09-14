"""Run with python -m app.ml: ingest, train, or predict. No web DB required."""
import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.providers.base import ProviderError
from app.providers.clinicaltrials import ClinicalTrialsCatalystProvider

from .data import snapshot, validate_snapshot
from .prediction import load_artifact, predict


def read_jsonl(path):
    rows = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("Expected an object")
                rows.append(row)
            except ValueError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return rows


def write_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = output.name
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Append full live snapshots without backdating")
    ingest.add_argument("--query", required=True)
    ingest.add_argument("--limit", type=int, default=1000)
    ingest.add_argument("--output", required=True)
    train_parser = commands.add_parser("train", help="Fit and evaluate with adjudicated outcomes")
    for name in ("snapshots", "labels", "train-until", "calibrate-until", "as-of", "output"):
        train_parser.add_argument(f"--{name}", required=True)
    predict_parser = commands.add_parser("predict", help="Score fresh snapshots using a JSON model")
    for name in ("snapshots", "model", "output"):
        predict_parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            existing = read_jsonl(args.output) if Path(args.output).exists() else []
            for row in existing:
                validate_snapshot(row)
            provider = ClinicalTrialsCatalystProvider(
                user_agent=os.getenv("CLINICALTRIALS_USER_AGENT", "ValoreaX-Research"))
            batch = provider.fetch_studies(query=args.query, limit=args.limit)
            observed = datetime.now(UTC).isoformat()
            # Preserve the earliest observation of each content version on reruns.
            keys = {(r["nct_id"], r["content_hash"]) for r in existing}
            added = 0
            for study in batch.studies:
                row = snapshot(study, observed, query=args.query)
                key = (row["nct_id"], row["content_hash"])
                if key not in keys:
                    existing.append(row)
                    keys.add(key)
                    added += 1
            write_atomic(args.output, "".join(json.dumps(r, allow_nan=False) + "\n" for r in existing))
            manifest = {"retrieved_at": observed, "query": args.query, "limit": args.limit,
                        "fetched": len(batch.studies), "added": added, "truncated": batch.truncated}
            write_atomic(args.output + ".manifest.json", json.dumps(manifest, indent=2))
            print(json.dumps(manifest))
        elif args.command == "train":
            from .training import train
            artifact = train(read_jsonl(args.snapshots), read_jsonl(args.labels),
                             train_until=args.train_until, calibrate_until=args.calibrate_until,
                             as_of=args.as_of)
            write_atomic(args.output, json.dumps(artifact, indent=2, allow_nan=False))
            print(json.dumps({"model_id": artifact["model_id"], "status": artifact["status"],
                              "evaluation": artifact["evaluation"]}))
        else:
            artifact = load_artifact(args.model)
            predictions = [predict(row, artifact) for row in read_jsonl(args.snapshots)]
            write_atomic(args.output, "".join(json.dumps(p, allow_nan=False) + "\n" for p in predictions))
            print(json.dumps({"predictions": len(predictions), "output": args.output}))
    except (ValueError, KeyError, TypeError, OSError, ProviderError, ImportError) as exc:
        parser.exit(2, f"Clinical ML: {exc}\n")


if __name__ == "__main__":
    main()
