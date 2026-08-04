import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { SignalResponse } from "../types";
import { signalColor } from "../format";
import { Badge, ErrorNote, Spinner } from "./ui";

// Runs the transparent signal engine. Optional manual overrides; everything else
// is auto-derived from stored SEC/catalyst/price data on the server.
export default function SignalPanel({ ticker, onRun }: { ticker: string; onRun?: () => void }) {
  const [valuationUpside, setValuationUpside] = useState<string>("");
  const [manualConfidence, setManualConfidence] = useState<string>("70");
  const [result, setResult] = useState<SignalResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = { auto_derive: true, persist: true };
      if (valuationUpside !== "") payload.valuation_upside = Number(valuationUpside) / 100;
      if (manualConfidence !== "") payload.manual_confidence = Number(manualConfidence) / 100;
      const res = await api.runSignal(ticker, payload);
      setResult(res);
      onRun?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="text-[11px] text-muted">Valuation upside % (optional)</span>
          <input
            type="number"
            value={valuationUpside}
            placeholder="e.g. 28"
            onChange={(e) => setValuationUpside(e.target.value)}
            className="mt-0.5 w-36 rounded-md border border-edge bg-ink px-2 py-1.5 font-mono text-sm outline-none focus:border-accent"
          />
        </label>
        <label className="block">
          <span className="text-[11px] text-muted">Analyst confidence %</span>
          <input
            type="number"
            value={manualConfidence}
            onChange={(e) => setManualConfidence(e.target.value)}
            className="mt-0.5 w-36 rounded-md border border-edge bg-ink px-2 py-1.5 font-mono text-sm outline-none focus:border-accent"
          />
        </label>
        <button
          onClick={run}
          disabled={busy}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-ink disabled:opacity-50"
        >
          {busy ? "Scoring…" : "Run signal"}
        </button>
      </div>

      <p className="text-[11px] text-muted">
        Catalyst outcome, event proximity, cash runway, and abnormal-return proxy are auto-derived
        server-side from stored data. Each run is persisted with its input snapshot.
      </p>

      {busy && <Spinner />}
      {error && <ErrorNote message={error} />}

      {result && (
        <div className="rounded-md border border-edge bg-ink/40 p-3">
          <div className="flex items-baseline gap-3">
            <span className={`text-2xl font-bold uppercase ${signalColor(result.signal)}`}>
              {result.signal}
            </span>
            <span className="font-mono text-sm text-muted">
              score {result.score > 0 ? "+" : ""}
              {result.score.toFixed(1)}
            </span>
            <span className="font-mono text-sm text-muted">
              conf {(result.confidence * 100).toFixed(0)}%
            </span>
          </div>

          {/* Explainable contribution breakdown */}
          <ul className="mt-3 space-y-1.5">
            {result.components.map((c) => (
              <li key={c.name} className="text-xs">
                <div className="mb-0.5 flex justify-between">
                  <span className="text-slate-300">{c.explanation}</span>
                  <span
                    className={`ml-2 font-mono ${
                      c.contribution >= 0 ? "text-long" : "text-short"
                    }`}
                  >
                    {c.contribution >= 0 ? "+" : ""}
                    {c.contribution.toFixed(1)}
                  </span>
                </div>
                {/* Contribution bar scaled to the component's weight. */}
                <div className="h-1 w-full overflow-hidden rounded bg-edge">
                  <div
                    className={c.contribution >= 0 ? "h-full bg-long" : "h-full bg-short"}
                    style={{ width: `${Math.min(100, (Math.abs(c.contribution) / c.weight) * 100)}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>

          {Object.keys(result.auto_derived).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              <span className="text-[11px] text-muted">Auto-derived:</span>
              {Object.entries(result.auto_derived).map(([k, v]) => (
                <Badge key={k} className="border-edge text-muted" title={v}>
                  {k}
                </Badge>
              ))}
            </div>
          )}

          {result.warnings.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-[11px] text-watch">
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}

          <p className="mt-2 text-[11px] italic text-slate-500">{result.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
