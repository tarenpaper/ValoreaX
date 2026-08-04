import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Company, Meta } from "../types";
import { Badge, Spinner } from "./ui";

interface Props {
  meta: Meta | null;
  activeTicker: string | null;
  onSelect: (ticker: string) => void;
}

// Search/select a ticker: lists already-ingested companies and can ingest a new
// one on demand (from the mock universe or, with SEC_PROVIDER=sec_edgar, live).
export default function TickerSearch({ meta, activeTicker, onSelect }: Props) {
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
  }, []);

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
    <div className="space-y-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ingest(input);
        }}
        className="flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            meta?.provider === "mock" ? "Ticker (e.g. VALX)" : "Any US ticker (e.g. PFE)"
          }
          className="w-full rounded-md border border-edge bg-ink px-3 py-2 text-sm uppercase tracking-wide outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-accent px-3 py-2 text-sm font-semibold text-ink disabled:opacity-50"
        >
          {busy ? "…" : "Load"}
        </button>
      </form>

      {error && <p className="text-xs text-short">{error}</p>}

      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[11px] text-muted">Sample:</span>
          {suggestions.map((t) => (
            <button
              key={t}
              onClick={() => ingest(t)}
              className="rounded border border-edge px-1.5 py-0.5 text-[11px] text-slate-300 hover:border-accent"
            >
              {t}
            </button>
          ))}
        </div>
      )}

      <div className="space-y-1">
        {companies.length === 0 && !busy && (
          <p className="text-xs text-muted">No companies loaded yet.</p>
        )}
        {busy && companies.length === 0 && <Spinner />}
        {companies.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.ticker)}
            className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition ${
              activeTicker === c.ticker
                ? "border-accent bg-accent/10"
                : "border-edge hover:border-slate-500"
            }`}
          >
            <span>
              <span className="font-mono font-semibold text-slate-100">{c.ticker}</span>
              <span className="ml-2 text-xs text-muted">{c.name}</span>
            </span>
            {c.is_example && (
              <Badge className="border-watch/40 bg-watch/10 text-watch">example</Badge>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
