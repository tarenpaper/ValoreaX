"""Scheduled signal-evaluation job.

Run on a schedule (cron / Task Scheduler) to score persisted signals against
catalyst outcomes that resolved *after* each signal's ``as_of_date``:

    python -m app.evaluate                 # evaluate every company
    python -m app.evaluate --company VALX   # evaluate one ticker
    python -m app.evaluate --json           # machine-readable output

The look-ahead guard lives in app.services.evaluation and is shared with the
`/signals/backtest` endpoint, so the job and the API can never diverge. This is
a directional-agreement scaffold, not a validated performance claim.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import Company
from app.services.evaluation import evaluate_all, evaluate_company


def run(company_ticker: str | None = None, as_json: bool = False) -> list[dict]:
    app = create_app()
    with app.app_context():
        if company_ticker:
            company = db.session.execute(
                select(Company).where(Company.ticker == company_ticker.upper())
            ).scalar_one_or_none()
            if company is None:
                raise SystemExit(f"Company {company_ticker!r} not found. Ingest it first.")
            results = [{"company_id": company.id, "ticker": company.ticker,
                        **evaluate_company(db.session, company.id)}]
        else:
            results = evaluate_all(db.session)

        if as_json:
            print(json.dumps(results, indent=2))
        else:
            _print_report(results)
        return results


def _print_report(results: list[dict]) -> None:
    # ASCII-only output so it renders on any console (Windows cp1252 included).
    if not results:
        print("No companies to evaluate.")
        return
    print(f"Signal evaluation - {len(results)} company(ies)\n")
    for r in results:
        rate = r["directional_agreement_rate"]
        rate_str = "n/a" if rate is None else f"{rate:.1%}"
        print(f"  {r['ticker']:<8} signals={r['signals_total']:<3} "
              f"evaluated={r['evaluated']:<3} agreement={rate_str}")
        for d in r["details"]:
            mark = "[agree]" if d["agreement"] else "[disagree]"
            print(f"      {mark} run#{d['signal_run_id']} {d['signal'].upper()} "
                  f"@ {d['as_of_date']} -> {d['next_resolved_outcome']} on {d['resolved_on']}")
    print("\nNote: look-ahead-safe scaffold; not a validated performance claim.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate persisted signals vs. resolved catalysts.")
    parser.add_argument("--company", help="Restrict to one ticker (default: all).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text report.")
    args = parser.parse_args()
    run(company_ticker=args.company, as_json=args.json)


if __name__ == "__main__":
    main()
