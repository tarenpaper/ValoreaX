"""Look-ahead-safe signal evaluation.

Scores each persisted `SignalRun`'s direction (LONG/SHORT) against the *first
catalyst outcome that resolved AFTER the run's ``as_of_date``* — never before.
This is the single home for the look-ahead guard, shared by the `/backtest`
endpoint and the scheduled evaluation job (`python -m app.evaluate`).

It is a directional-agreement scaffold, not a validated performance claim: when
no post-signal catalysts have resolved yet, the rate is honestly ``None``.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import CatalystEvent, Company, SignalRun

METHODOLOGY = (
    "For each persisted signal, compare its direction (LONG/SHORT) against the "
    "first catalyst outcome that resolved AFTER the signal's as_of_date."
)


def _anchor_date(run: SignalRun) -> date:
    """The point in time a run's inputs represent (guards against look-ahead)."""
    return run.as_of_date or (run.created_at.date() if run.created_at else date.today())


def evaluate_company(session, company_id: int) -> dict:
    """Return directional-agreement stats for one company (look-ahead-safe)."""
    runs = session.execute(
        select(SignalRun).where(SignalRun.company_id == company_id)
    ).scalars().all()
    catalysts = session.execute(
        select(CatalystEvent).where(CatalystEvent.company_id == company_id)
    ).scalars().all()

    evaluated = 0
    agreements = 0
    details = []
    for run in runs:
        anchor = _anchor_date(run)
        future = [
            c for c in catalysts
            if c.outcome in {"positive", "negative"} and c.actual_date and c.actual_date > anchor
        ]
        if not future:
            continue
        future.sort(key=lambda c: c.actual_date)
        outcome = future[0].outcome
        agree = (run.signal == "long" and outcome == "positive") or (
            run.signal == "short" and outcome == "negative"
        )
        evaluated += 1
        agreements += int(agree)
        details.append({
            "signal_run_id": run.id,
            "signal": run.signal,
            "as_of_date": anchor.isoformat(),
            "next_resolved_outcome": outcome,
            "resolved_on": future[0].actual_date.isoformat(),
            "agreement": agree,
        })

    return {
        "signals_total": len(runs),
        "evaluated": evaluated,
        "agreements": agreements,
        "directional_agreement_rate": round(agreements / evaluated, 3) if evaluated else None,
        "note": (
            "No resolved post-signal catalysts yet — agreement rate is unavailable "
            "(no fabricated results)." if evaluated == 0 else
            "Small-sample scaffold; not a validated performance claim."
        ),
        "details": details,
    }


def evaluate_all(session) -> list[dict]:
    """Evaluate every company; used by the scheduled job."""
    companies = session.execute(select(Company).order_by(Company.ticker)).scalars().all()
    results = []
    for company in companies:
        stats = evaluate_company(session, company.id)
        results.append({"company_id": company.id, "ticker": company.ticker, **stats})
    return results
