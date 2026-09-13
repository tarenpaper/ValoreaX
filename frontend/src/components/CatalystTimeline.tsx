import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Catalyst } from "../types";
import { ErrorNote, Icon, Spinner, TerminalPanel } from "./ui";

const OUTCOMES = ["pending", "positive", "negative", "mixed", "withdrawn"];

const OUTCOME_STYLE: Record<string, string> = {
  positive: "border-primary/50 bg-primary/20 text-primary",
  negative: "border-error/50 bg-error/20 text-error",
  mixed: "border-caution/50 bg-caution/10 text-caution",
  withdrawn: "border-outline-variant bg-surface-container text-on-surface-variant",
  pending: "border-outline-variant bg-surface-container text-on-surface-variant",
};

const DOT: Record<string, string> = {
  positive: "bg-primary shadow-[0_0_4px_rgba(56,225,198,0.8)]",
  negative: "bg-error",
  mixed: "bg-caution",
  withdrawn: "bg-outline-variant",
  pending: "bg-outline-variant",
};

export default function CatalystTimeline({
  ticker,
  catalystProvider,
  className = "",
}: {
  ticker: string;
  catalystProvider: string | null;
  className?: string;
}) {
  const [items, setItems] = useState<Catalyst[]>([]);
  const [ingesting, setIngesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const canIngest = catalystProvider === "clinicaltrials" || catalystProvider === "mock";

  const refresh = useCallback(async (t: string) => {
    setLoading(true);
    try {
      setItems((await api.listCatalysts(t)).catalysts);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh(ticker);
  }, [ticker, refresh]);

  async function ingest() {
    setIngesting(true);
    setError(null);
    try {
      await api.ingestCatalysts(ticker);
      await refresh(ticker);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setIngesting(false);
    }
  }

  async function setOutcome(c: Catalyst, outcome: string) {
    await api.updateCatalyst(c.id, { outcome });
    await refresh(ticker);
  }

  const sorted = [...items].sort((a, b) =>
    (b.actual_date ?? b.expected_date ?? "").localeCompare(a.actual_date ?? a.expected_date ?? ""),
  );

  return (
    <TerminalPanel
      title="CLINICAL CATALYSTS"
      className={className}
      bodyClassName="flex-1 min-h-0 overflow-y-auto overscroll-contain p-4 relative"
      action={
        <button
          onClick={ingest}
          disabled={!canIngest || ingesting}
          title={canIngest ? `Fetch trials (${catalystProvider})` : "Set CATALYST_PROVIDER to enable"}
          className="text-on-surface-variant hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Icon name={ingesting ? "progress_activity" : "download"} size="sm" className={ingesting ? "animate-spin" : ""} />
        </button>
      }
    >
      {error && <ErrorNote message={error} />}
      {loading && items.length === 0 ? (
        <Spinner label="Loading catalysts…" />
      ) : sorted.length === 0 ? (
        <p className="grid h-full place-items-center text-center font-data-sm text-data-sm text-on-surface-variant">
          {canIngest ? "No catalysts yet — use ↓ to fetch trials." : "No catalysts. Enable a provider to fetch."}
        </p>
      ) : (
        <div className="relative">
          <div className="absolute bottom-2 left-[39px] top-2 w-[1px] bg-outline-variant" />
          <div className="flex flex-col gap-4">
            {sorted.map((c) => {
              const dated = c.actual_date ?? c.expected_date;
              const resolved = !!c.actual_date;
              const highlight = c.outcome === "positive";
              return (
                <div key={c.id} className="flex items-start gap-4">
                  <div className="w-12 pt-0.5 text-right">
                    <span className="block font-data-sm text-[10px] text-on-surface-variant">
                      {dated ?? "TBD"}
                    </span>
                    <span className="font-data-sm text-[8px] text-outline">{resolved ? "ACT" : "EST"}</span>
                  </div>
                  <div className={`mt-1.5 h-[7px] w-[7px] shrink-0 rounded-full border border-surface ${DOT[c.outcome]}`} />
                  <div
                    className={`min-w-0 flex-1 break-words rounded-sm border p-2 ${
                      highlight ? "border-primary/30 bg-primary/5" : "border-outline-variant bg-surface"
                    }`}
                  >
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <span className={`font-data-tabular text-[11px] ${highlight ? "text-primary" : "text-on-surface"}`}>
                        {c.drug_program}
                      </span>
                      <select
                        value={c.outcome}
                        onChange={(e) => setOutcome(c, e.target.value)}
                        className={`rounded-sm border px-1 py-[1px] font-data-sm text-[8px] uppercase outline-none ${OUTCOME_STYLE[c.outcome]}`}
                      >
                        {OUTCOMES.map((o) => (
                          <option key={o} value={o} className="bg-surface text-on-surface">
                            {o}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="mb-1 font-body-main text-[11px] text-on-surface-variant">
                      {c.event_type.replace(/_/g, " ")}
                      {c.trial_phase ? ` · ${c.trial_phase}` : ""}
                      {c.indication ? ` — ${c.indication}` : ""}
                    </div>
                    {c.source_url && (
                      <a
                        href={c.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-block rounded-sm border border-outline-variant bg-surface-container px-1 font-data-tabular text-[8px] text-on-surface-variant hover:text-primary"
                      >
                        {c.external_id ?? "source"} ↗
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </TerminalPanel>
  );
}
