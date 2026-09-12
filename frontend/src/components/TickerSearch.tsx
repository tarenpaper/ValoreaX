import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Company, Meta } from "../types";
import { Icon } from "./ui";

interface Props {
  meta: Meta | null;
  refreshKey: number;
  activeTicker: string | null;
  onSelect: (ticker: string) => void;
}

// Sidebar watchlist: lists ingested companies and ingests a new ticker on demand
// (from the mock universe, or live via SEC_PROVIDER=sec_edgar).
export default function TickerSearch({ meta, activeTicker, onSelect, refreshKey }: Props) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const res = await api.listCompanies();
    setCompanies(res.companies);
    setSuggestions(res.available_mock_tickers);
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [refreshKey]);

  async function ingest(ticker: string) {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setBusy(true);
    setError(null);
    try {
      await api.ingestCompany(t);
      await refresh();
      setInput("");
      onSelect(t);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col">
      {/* Search */}
      <div className="px-4 pb-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ingest(input);
          }}
          className="flex items-center gap-2 rounded-xl border border-outline-variant bg-surface px-2 py-1 focus-within:border-primary"
        >
          <Icon name="search" size="xs" className="text-on-surface-variant" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={meta?.provider === "mock" ? "Ticker, e.g. VALX" : "Any US ticker, e.g. PFE"}
            className="w-full bg-transparent p-0 font-data-tabular text-data-tabular uppercase tracking-wide text-on-surface placeholder:normal-case placeholder:text-on-surface-variant/50 focus:ring-0 focus:outline-none"
          />
          {busy && <Icon name="progress_activity" size="xs" className="animate-spin text-primary" />}
        </form>
        {error && <p className="mt-1 font-data-sm text-data-sm text-error">{error}</p>}
        {suggestions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {suggestions.map((t) => (
              <button
                key={t}
                onClick={() => ingest(t)}
                className="rounded-xl border border-outline-variant px-1.5 py-0.5 font-data-sm text-data-sm text-on-surface-variant hover:border-primary hover:text-primary"
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Watchlist items */}
      <div className="flex flex-col gap-1">
        {companies.length === 0 && !busy && (
          <p className="px-4 py-3 font-data-sm text-data-sm text-on-surface-variant">
            No companies loaded yet.
          </p>
        )}
        {companies.map((c) => {
          const active = activeTicker === c.ticker;
          return (
            <button
              key={c.id}
              onClick={() => onSelect(c.ticker)}
              className={`flex items-center justify-between px-4 py-2 text-left transition-colors hover:bg-surface-container-high ${
                active
                  ? "border-l-2 border-primary bg-surface-container"
                  : "border-l-2 border-transparent"
              }`}
            >
              <div className="flex flex-col overflow-hidden">
                <span
                  className={`font-data-tabular text-data-tabular ${active ? "text-primary" : "text-on-surface"}`}
                >
                  {c.ticker}
                </span>
                <span className="w-28 truncate font-data-sm text-data-sm text-on-surface-variant">
                  {c.name}
                </span>
              </div>
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  c.source === "mock" || c.is_example ? "bg-outline" : "bg-primary"
                }`}
                title={c.source}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}
