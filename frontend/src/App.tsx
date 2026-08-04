import { useEffect, useState } from "react";
import { api } from "./api/client";
import type { Meta } from "./types";
import TickerSearch from "./components/TickerSearch";
import { Panel } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Backtest from "./pages/Backtest";

type Tab = "dashboard" | "backtest";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [ticker, setTicker] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("dashboard");

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  return (
    <div className="min-h-full">
      {/* Top bar */}
      <header className="sticky top-0 z-10 border-b border-edge bg-ink/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between px-4 py-2.5">
          <div className="flex items-center gap-3">
            <span className="font-mono text-lg font-bold tracking-tight text-accent">ValoreaX</span>
            <span className="hidden text-xs text-muted sm:inline">
              Healthcare Equity Research · local-first
            </span>
          </div>
          <nav className="flex items-center gap-1 text-sm">
            {(["dashboard", "backtest"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-md px-3 py-1.5 capitalize ${
                  tab === t ? "bg-edge text-slate-100" : "text-muted hover:text-slate-200"
                }`}
              >
                {t}
              </button>
            ))}
            {meta && (
              <span className="ml-2 rounded border border-edge px-2 py-1 text-[11px] text-muted">
                provider: <span className="text-slate-300">{meta.provider}</span>
              </span>
            )}
          </nav>
        </div>
      </header>

      {/* Disclaimer banner */}
      <div className="border-b border-watch/20 bg-watch/5 px-4 py-1.5 text-center text-[11px] text-watch/90">
        Educational research tool — not investment advice, no guaranteed returns. Some data may be
        clearly-labelled sample data. Verify against primary SEC filings.
      </div>

      <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[280px_1fr]">
        {/* Sidebar */}
        <aside className="lg:sticky lg:top-[52px] lg:h-fit">
          <Panel title="Companies">
            <TickerSearch meta={meta} activeTicker={ticker} onSelect={setTicker} />
          </Panel>
        </aside>

        {/* Main */}
        <main className="min-w-0">
          {tab === "dashboard" ? <Dashboard ticker={ticker} /> : <Backtest ticker={ticker} />}
        </main>
      </div>

      <footer className="mx-auto max-w-[1400px] px-4 py-6 text-center text-[11px] text-slate-600">
        {meta?.disclaimer}
      </footer>
    </div>
  );
}
