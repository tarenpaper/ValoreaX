import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { BacktestResponse, SignalRun } from "../types";
import { signalColor } from "../format";
import { Badge, ErrorNote, Panel, Spinner, Stat } from "../components/ui";

// Placeholder evaluation page: measures directional agreement between persisted
// pre-event signals and later catalyst outcomes, in a look-ahead-safe way. It
// reports a rate ONLY when real evaluation data exists (never a fabricated number).
export default function Backtest({ ticker }: { ticker: string | null }) {
  const [bt, setBt] = useState<BacktestResponse | null>(null);
  const [runs, setRuns] = useState<SignalRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    setError(null);
    try {
      const [b, r] = await Promise.all([api.backtest(t), api.listSignals(t)]);
      setBt(b);
      setRuns(r.signal_runs);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ticker) load(ticker);
  }, [ticker, load]);

  if (!ticker) {
    return <div className="grid h-full place-items-center text-muted">Select a company first.</div>;
  }
  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;
  if (!bt) return null;

  return (
    <div className="space-y-4">
      <Panel title={`Backtest / evaluation — ${bt.ticker}`}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Signals total" value={bt.signals_total} />
          <Stat label="Evaluated" value={bt.evaluated} />
          <Stat
            label="Directional agreement"
            value={
              bt.directional_agreement_rate === null
                ? "N/A"
                : `${(bt.directional_agreement_rate * 100).toFixed(0)}%`
            }
          />
          <Stat label="Look-ahead" value="guarded" sub="post-signal outcomes only" />
        </div>
        <p className="mt-3 rounded-md border border-edge bg-ink/40 p-3 text-xs text-muted">
          <span className="font-semibold text-slate-300">Methodology.</span> {bt.methodology}
        </p>
        <p className="mt-2 text-[11px] italic text-watch">{bt.note}</p>
      </Panel>

      <Panel title="Evaluated signals">
        {bt.details.length === 0 ? (
          <p className="text-xs text-muted">
            No post-signal catalyst outcomes to score yet. Persist signals, then resolve catalysts
            with an actual date to populate this.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-muted">
                <th className="py-2 pr-3">Run</th>
                <th className="py-2 pr-3">Signal</th>
                <th className="py-2 pr-3">As of</th>
                <th className="py-2 pr-3">Next outcome</th>
                <th className="py-2 pr-3">Resolved</th>
                <th className="py-2">Agreement</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              {bt.details.map((d) => (
                <tr key={d.signal_run_id}>
                  <td className="py-2 pr-3 font-mono text-muted">#{d.signal_run_id}</td>
                  <td className={`py-2 pr-3 font-semibold uppercase ${signalColor(d.signal)}`}>
                    {d.signal}
                  </td>
                  <td className="py-2 pr-3 font-mono text-muted">{d.as_of_date}</td>
                  <td className="py-2 pr-3">{d.next_resolved_outcome}</td>
                  <td className="py-2 pr-3 font-mono text-muted">{d.resolved_on}</td>
                  <td className="py-2">
                    <Badge
                      className={
                        d.agreement
                          ? "border-long/40 bg-long/10 text-long"
                          : "border-short/40 bg-short/10 text-short"
                      }
                    >
                      {d.agreement ? "agree" : "disagree"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Persisted signal runs">
        {runs.length === 0 ? (
          <p className="text-xs text-muted">No signal runs persisted for this company.</p>
        ) : (
          <ul className="space-y-1.5">
            {runs.map((r) => (
              <li
                key={r.id}
                className="flex items-center justify-between rounded-md border border-edge px-3 py-1.5 text-sm"
              >
                <span className="flex items-center gap-2">
                  <span className={`font-semibold uppercase ${signalColor(r.signal)}`}>
                    {r.signal}
                  </span>
                  <span className="font-mono text-xs text-muted">
                    score {r.score > 0 ? "+" : ""}
                    {r.score.toFixed(1)} · conf {(r.confidence * 100).toFixed(0)}%
                  </span>
                </span>
                <span className="font-mono text-xs text-muted">
                  as of {r.as_of_date ?? "—"} · {r.engine_version}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
