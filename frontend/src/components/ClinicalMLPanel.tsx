import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ClinicalMLView } from "../types";
import { ErrorNote, Spinner } from "./ui";

export default function ClinicalMLPanel({ ticker, onIngest }: { ticker: string; onIngest?: () => void }) {
  const [data, setData] = useState<ClinicalMLView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [visible, setVisible] = useState(12);
  const generation = useRef(0);

  useEffect(() => {
    const current = ++generation.current;
    setData(null);
    setError(null);
    setVisible(12);
    setBusy(false);
    api.clinicalML(ticker).then(result => {
      if (generation.current === current) setData(result);
    }).catch(err => {
      if (generation.current === current) setError(err instanceof Error ? err.message : "Trial data unavailable.");
    });
    return () => { ++generation.current; };
  }, [ticker]);

  async function ingest() {
    const current = ++generation.current;
    setBusy(true);
    setError(null);
    try {
      const result = await api.ingestClinicalML(ticker);
      if (generation.current === current) {
        setData(result);
        onIngest?.();
      }
    } catch (err) {
      if (generation.current === current) setError(err instanceof Error ? err.message : "Ingestion failed.");
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }

  return <section className="rounded-2xl border border-outline-variant bg-surface-container-lowest p-6" aria-label="Clinical success model">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><h2 className="text-lg font-semibold">Clinical success model</h2>
        <p className="mt-1 text-sm text-on-surface-variant">Will a trial meet its primary endpoints?</p></div>
      <button onClick={ingest} disabled={busy || !data?.ingestion_enabled}
        className="rounded-lg border border-outline-variant px-4 py-2 text-sm hover:text-primary disabled:opacity-40">
        {busy ? "Ingesting registry data…" : "Ingest trial evidence"}
      </button>
    </div>
    {error && <div className="mt-4"><ErrorNote message={error} /></div>}
    {!data && !error && <Spinner label="Loading clinical model coverage…" />}
    {data && <>
      <div className="my-5 rounded-xl bg-surface-container-low p-4 text-sm">
        <p className="font-semibold">{data.model_status === "research_candidate" ? "Experimental model · research estimates" : data.model_status === "evaluation_failed" ? "Model withheld · evaluation did not pass" : "Awaiting a trained model"}</p>
        <p className="mt-1 text-on-surface-variant">{data.model_error ?? (data.model_status === "not_configured"
          ? "Registry evidence can be collected now. Success estimates will appear after a model is trained on reviewed outcomes and passes evaluation on later trials."
          : "Estimates concern trial endpoints. They do not measure regulatory approval or the success of an entire drug program.")}</p>
        {data.evaluation && <p className="mt-2 text-xs text-on-surface-variant">Held-out trials: {data.evaluation.model.n} · Brier score: {data.evaluation.model.brier.toFixed(3)} · Phase baseline: {data.evaluation.phase_baseline.brier.toFixed(3)} (lower is better)</p>}
      </div>
      <div className="mb-3 flex flex-wrap gap-3 text-xs text-on-surface-variant">
        <span>{data.trials.length} registry studies</span>
        {data.retrieved_at && <span>Retrieved {new Date(data.retrieved_at).toLocaleString()}</span>}
        {data.truncated && <span>Partial cohort · ingestion limit reached</span>}
      </div>
      {data.trials.length === 0 && <p className="py-4 text-sm text-on-surface-variant">{data.ingestion_enabled ? "Ingest trial evidence to inspect drug interventions, indications, and prediction coverage." : "Enable the ClinicalTrials.gov provider to collect real trial evidence."}</p>}
      <div className="grid gap-3 lg:grid-cols-2">
        {data.trials.slice(0, visible).map(trial => <article key={trial.nct_id} className="rounded-xl border border-outline-variant p-4">
          <div className="flex items-start justify-between gap-3">
            <a href={trial.source_url} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-primary hover:underline">{trial.nct_id} ↗</a>
            <span className="text-xs text-on-surface-variant">{trial.phase.replaceAll("PHASE", "Phase ").replaceAll("+", " / ")}</span>
          </div>
          <p className="mt-2 text-sm font-medium">{trial.interventions.join(" / ") || trial.title || "Unnamed intervention"}</p>
          <p className="mt-1 text-xs text-on-surface-variant">{trial.conditions.join(" · ") || "Indication unavailable"}</p>
          <div className="mt-3 border-t border-outline-variant pt-3">
            {trial.probability !== null ? <p className="text-lg font-semibold">{(trial.probability * 100).toFixed(0)}% <span className="text-xs font-normal text-on-surface-variant">experimental endpoint estimate</span></p>
              : <p className="text-sm text-on-surface-variant">Estimate unavailable</p>}
            {trial.reasons.length > 0 && <p className="mt-1 text-xs text-on-surface-variant">{trial.reasons.join(" ")}</p>}
            {trial.drivers.length > 0 && <details className="mt-2 text-xs text-on-surface-variant"><summary className="cursor-pointer">Model factors</summary>
              <p className="mt-2">Associations in training data; these do not establish causes.</p>
              <ul className="mt-2 space-y-1">{trial.drivers.map(driver => <li key={driver.feature}>{driver.feature.replaceAll("_", " ")}: {driver.log_odds_contribution > 0 ? "raises" : "lowers"} the estimate</li>)}</ul>
            </details>}
          </div>
        </article>)}
      </div>
      {data.trials.length > visible && <button onClick={() => setVisible(value => value + 12)} className="mt-4 text-sm text-primary">Show more trials</button>}
      <details className="mt-5 text-xs text-on-surface-variant"><summary className="cursor-pointer">Coverage and limitations</summary><ul className="mt-2 list-disc space-y-1 pl-4">{data.limitations.map(note => <li key={note}>{note}</li>)}</ul></details>
    </>}
  </section>;
}
