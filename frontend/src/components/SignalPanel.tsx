import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { SignalResponse } from "../types";
import { signalColor } from "../format";
import { ErrorNote, Icon, Spinner, TerminalPanel } from "./ui";

// Short display labels for the engine's component names.
const FACTOR_LABEL: Record<string, string> = {
  valuation: "Valuation",
  catalyst_outcome: "Catalyst Path",
  exclusivity_runway: "Patent Cliff",
  financial_health: "Financial Health",
  analyst_consensus: "Analyst Cons.",
  abnormal_return: "Momentum",
  news_sentiment: "News",
};

// The valuation component is only meaningful next to what it was measured against.
const BASIS_LABEL: Record<string, string> = {
  peer_median: "vs peers",
  own_range: "vs own range",
  manual_upside: "manual",
};

export default function SignalPanel({ ticker, className = "" }: { ticker: string; className?: string }) {
  const [result, setResult] = useState<SignalResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (persist: boolean) => {
      setBusy(true);
      setError(null);
      try {
        setResult(await api.runSignal(ticker, { auto_derive: true, persist }));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [ticker],
  );

  useEffect(() => {
    setResult(null);
    run(false); // display-only run on load; the save action persists a run
  }, [ticker, run]);

  return (
    <TerminalPanel
      title="SIGNAL VERDICT"
      className={className}
      bodyClassName="p-4 flex-1 flex flex-col min-h-0"
      action={
        <button
          onClick={() => run(true)}
          disabled={busy}
          title="Re-run and save this signal"
          className="text-on-surface-variant hover:text-primary disabled:opacity-40"
        >
          <Icon name={busy ? "progress_activity" : "refresh"} size="sm" className={busy ? "animate-spin" : ""} />
        </button>
      }
    >
      {error ? (
        <ErrorNote message={error} />
      ) : !result ? (
        <Spinner label="Scoring…" />
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="mb-1 font-label-caps text-label-caps uppercase text-on-surface-variant">
                ValoreaX Score
              </div>
              <div className={`font-display-ticker text-[32px] uppercase leading-none ${signalColor(result.signal)}`}>
                {result.signal}
              </div>
            </div>
            <div className="text-right">
              <div className="font-data-tabular text-[20px] text-on-surface">
                {result.score > 0 ? "+" : ""}
                {result.score.toFixed(1)}
              </div>
              <div className="font-data-sm text-data-sm text-on-surface-variant">
                Conf: {(result.confidence * 100).toFixed(0)}%
              </div>
            </div>
          </div>

          <div className="mb-3 border-b border-outline-variant pb-1 font-label-caps text-label-caps uppercase text-on-surface-variant">
            Factor Explainer
          </div>

          <div className="flex flex-1 flex-col gap-2 overflow-y-auto pr-1">
            {result.components.map((comp) => {
              const pos = comp.contribution >= 0;
              const width = Math.min(50, (Math.abs(comp.contribution) / comp.weight) * 50);
              return (
                <div key={comp.name} className="flex items-center gap-2" title={comp.explanation}>
                  <div className="w-1/3 truncate font-data-sm text-data-sm text-on-surface">
                    {FACTOR_LABEL[comp.name] ?? comp.name}
                    {comp.basis && BASIS_LABEL[comp.basis] && (
                      <span className="ml-1 text-[9px] text-on-surface-variant">
                        {BASIS_LABEL[comp.basis]}
                      </span>
                    )}
                  </div>
                  <div className="relative h-3 flex-1 overflow-hidden rounded-sm bg-surface-container">
                    <div className="absolute left-1/2 z-10 h-full w-[1px] bg-outline-variant" />
                    <div
                      className={`absolute h-full ${pos ? "left-1/2 bg-primary/80" : "right-1/2 bg-error/80"}`}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                  <div
                    className={`w-9 text-right font-data-tabular text-[10px] ${pos ? "text-primary" : "text-error"}`}
                  >
                    {pos ? "+" : ""}
                    {comp.contribution.toFixed(1)}
                  </div>
                </div>
              );
            })}
            {result.components.length === 0 && (
              <p className="font-data-sm text-data-sm text-on-surface-variant">
                No inputs yet — fetch analyst ratings and catalysts to feed the signal.
              </p>
            )}

            {/* A missing factor is not a neutral one, so say which are absent and why. */}
            {result.skipped?.length > 0 && (
              <details className="mt-2 border-t border-outline-variant pt-2">
                <summary className="cursor-pointer font-data-sm text-[10px] text-on-surface-variant">
                  {result.skipped.length} factor{result.skipped.length === 1 ? "" : "s"} not scored
                </summary>
                <ul className="mt-1.5 space-y-1">
                  {result.skipped.map((entry) => (
                    <li key={entry.name} className="font-data-sm text-[10px] text-on-surface-variant">
                      <span className="text-on-surface">
                        {FACTOR_LABEL[entry.name] ?? entry.name}
                      </span>{" "}
                      — {entry.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {result.warnings?.length > 0 && (
              <ul className="mt-2 space-y-1">
                {result.warnings.map((warning) => (
                  <li key={warning} className="font-data-sm text-[10px] text-caution">
                    {warning}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </TerminalPanel>
  );
}
