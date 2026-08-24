import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { WatchlistRow } from "../types";
import { formatPct, formatPrice, signalColor } from "../format";
import { ErrorNote, Icon, Spinner } from "../components/ui";

const STATUS_STYLE: Record<string, { dot: string; border: string; word: string }> = {
  upcoming: { dot: "bg-tertiary-fixed-dim", border: "border-outline", word: "Upcoming" },
  recent: { dot: "bg-primary", border: "border-outline", word: "Recent" },
  overdue: { dot: "bg-error", border: "border-error-container", word: "Overdue" },
  none: { dot: "bg-outline-variant", border: "border-outline-variant", word: "None" },
};

export default function Watchlist({ onOpen }: { onOpen: (ticker: string) => void }) {
  const [rows, setRows] = useState<WatchlistRow[]>([]);
  const [asOf, setAsOf] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Set<string>>(new Set());

  function setRowPending(key: string, on: boolean) {
    setPending((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  async function rowAction(row: WatchlistRow, action: "sync" | "ingest") {
    const key = `${row.id}:${action}`;
    setRowPending(key, true);
    setError(null);
    try {
      if (action === "sync") await api.syncPrices(row.ticker);
      else await api.ingestCatalysts(row.ticker);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRowPending(key, false);
    }
  }

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.watchlist();
      setRows(res.companies);
      setAsOf(res.as_of);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function addTicker() {
    const t = newTicker.trim().toUpperCase();
    if (!t) return;
    setBusy(true);
    setError(null);
    try {
      await api.ingestCompany(t);
      setNewTicker("");
      setAdding(false);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const shown = rows.filter(
    (r) =>
      !filter ||
      r.ticker.toLowerCase().includes(filter.toLowerCase()) ||
      r.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      {/* Page header */}
      <div className="flex items-end justify-between border-b border-outline-variant pb-2">
        <div>
          <h2 className="mb-1 font-label-caps text-label-caps uppercase tracking-wider text-on-surface-variant">
            Personalized View
          </h2>
          <h1 className="font-headline-panel text-2xl font-bold text-on-surface">Investment Watchlist</h1>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 rounded-sm border border-outline-variant bg-surface px-2 py-1">
            <Icon name="filter_list" size="xs" className="text-on-surface-variant" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter"
              className="w-24 bg-transparent p-0 font-data-tabular text-data-tabular text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none focus:ring-0"
            />
          </label>
          <button
            onClick={() => setAdding((a) => !a)}
            className="flex items-center gap-1 rounded-sm bg-primary-container px-3 py-1 font-data-tabular text-data-tabular text-on-primary-container transition hover:opacity-90"
          >
            <Icon name="add" size="xs" /> New Ticker
          </button>
        </div>
      </div>

      {adding && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addTicker();
          }}
          className="flex items-center gap-2 rounded-sm border border-outline-variant bg-surface-container p-2"
        >
          <input
            autoFocus
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value)}
            placeholder="Ticker to add (e.g. PFE) — ingests live from SEC"
            className="flex-1 rounded-sm border border-outline-variant bg-background px-2 py-1 font-data-tabular text-data-tabular uppercase tracking-wide text-on-surface focus:border-primary focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-sm bg-primary-container px-3 py-1 font-data-tabular text-data-tabular font-semibold text-on-primary disabled:opacity-50"
          >
            {busy ? "Adding…" : "Add"}
          </button>
        </form>
      )}

      {error && <ErrorNote message={error} />}

      {/* Watchlist panel */}
      <div className="terminal-panel flex flex-col overflow-hidden rounded-sm border border-outline-variant">
        <div className="flex h-8 shrink-0 items-center border-b border-outline-variant bg-surface-container-highest px-4">
          <span className="font-label-caps text-label-caps uppercase text-on-surface">
            Active Tracking List
          </span>
          <div className="ml-auto flex items-center gap-2">
            <span className="font-data-sm text-data-sm text-on-surface-variant">
              {asOf ? `As of ${asOf}` : ""}
            </span>
            <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
          </div>
        </div>

        {loading && rows.length === 0 ? (
          <div className="p-4">
            <Spinner label="Loading watchlist…" />
          </div>
        ) : shown.length === 0 ? (
          <p className="p-8 text-center font-data-sm text-data-sm text-on-surface-variant">
            {rows.length === 0
              ? "No companies tracked yet. Use “New Ticker” to add one."
              : "No matches for this filter."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-outline-variant bg-surface-container-low font-label-caps text-label-caps uppercase text-on-surface-variant">
                  <th className="w-24 px-4 py-2 font-normal">Ticker</th>
                  <th className="w-32 px-4 py-2 font-normal">Price / Chg</th>
                  <th className="px-4 py-2 font-normal">Trend (7D)</th>
                  <th className="w-56 px-4 py-2 font-normal">Clinical Status</th>
                  <th className="w-44 px-4 py-2 text-right font-normal">Signal / Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant font-data-tabular text-data-tabular text-on-surface">
                {shown.map((r) => {
                  const st = STATUS_STYLE[r.clinical_status.state] ?? STATUS_STYLE.none;
                  const up = (r.change_7d ?? r.change_pct ?? 0) >= 0;
                  return (
                    <tr key={r.id} className="group h-10 transition-colors hover:bg-surface-container-high">
                      <td className="px-4 py-1">
                        <button
                          onClick={() => onOpen(r.ticker)}
                          className="font-bold text-primary hover:underline"
                          title={r.name}
                        >
                          {r.ticker}
                        </button>
                      </td>
                      <td className="px-4 py-1">
                        <div className="flex flex-col">
                          <span>{r.price !== null ? formatPrice(r.price) : "—"}</span>
                          {r.change_pct !== null && (
                            <span className={`text-[10px] ${r.change_pct >= 0 ? "text-primary" : "text-error"}`}>
                              {r.change_pct >= 0 ? "+" : ""}
                              {formatPct(r.change_pct)}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-1">
                        <Sparkline series={r.series} up={up} />
                      </td>
                      <td className="px-4 py-1">
                        <span
                          className={`inline-flex items-center gap-1 rounded-sm border bg-surface px-2 py-0.5 font-data-sm text-data-sm text-on-surface ${st.border}`}
                        >
                          <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />
                          {st.word}
                          {r.clinical_status.state !== "none" && (
                            <span className="text-on-surface-variant">| {r.clinical_status.label}</span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-1">
                        <div className="flex items-center justify-end gap-1.5">
                          {r.signal && (
                            <span className={`mr-1 font-data-sm text-data-sm uppercase ${signalColor(r.signal)}`}>
                              {r.signal === "watchlist" ? "watch" : r.signal}
                            </span>
                          )}
                          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                            <RowIcon
                              icon="sync"
                              title="Sync prices"
                              busy={pending.has(`${r.id}:sync`)}
                              onClick={() => rowAction(r, "sync")}
                            />
                            <RowIcon
                              icon="vaccines"
                              title="Ingest clinical trials"
                              busy={pending.has(`${r.id}:ingest`)}
                              onClick={() => rowAction(r, "ingest")}
                            />
                          </div>
                          <button
                            onClick={() => onOpen(r.ticker)}
                            title="Open in dashboard"
                            className="rounded-sm border border-transparent p-1 text-on-surface-variant hover:border-outline-variant hover:text-primary"
                          >
                            <Icon name="open_in_new" className="text-[16px]" size="xs" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="font-footer-disclaimer text-footer-disclaimer text-on-surface-variant">
        Prices and clinical status reflect stored data — sync prices and ingest catalysts per company to
        populate them. Educational research, not investment advice.
      </p>
    </div>
  );
}

function RowIcon({
  icon,
  title,
  busy,
  onClick,
}: {
  icon: string;
  title: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      title={title}
      className="rounded-sm border border-transparent p-1 text-on-surface-variant hover:border-outline-variant hover:text-primary disabled:opacity-60"
    >
      <Icon
        name={busy ? "progress_activity" : icon}
        className={`text-[16px] ${busy ? "animate-spin" : ""}`}
        size="xs"
      />
    </button>
  );
}

function Sparkline({ series, up }: { series: number[]; up: boolean }) {
  if (series.length < 2) return <span className="font-data-sm text-data-sm text-on-surface-variant">—</span>;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  const n = series.length;
  const pts = series.map((v, i) => `${(i / (n - 1)) * 120},${19 - ((v - min) / span) * 18}`).join(" ");
  return (
    <svg width="120" height="20" viewBox="0 0 120 20" className={`fill-none stroke-[1.5px] ${up ? "stroke-primary" : "stroke-error"}`}>
      <polyline points={pts} />
    </svg>
  );
}
