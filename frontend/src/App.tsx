import { useEffect, useState } from "react";
import { api } from "./api/client";
import type { Meta } from "./types";
import TickerSearch from "./components/TickerSearch";
import { Icon } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Backtest from "./pages/Backtest";
import Watchlist from "./pages/Watchlist";
import News from "./pages/News";

type Tab = "dashboard" | "news" | "watchlist" | "backtest";

const NAV: Array<{ tab: Tab; label: string; icon: string }> = [
  { tab: "dashboard", label: "Dashboard", icon: "dashboard" },
  { tab: "news", label: "News", icon: "article" },
  { tab: "watchlist", label: "Watchlist", icon: "pie_chart" },
  { tab: "backtest", label: "Backtest", icon: "query_stats" },
];

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [ticker, setTicker] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("dashboard");

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  const pills: Array<{ label: string; live: boolean }> = [
    { label: "SEC", live: meta?.provider === "sec_edgar" },
    { label: "Trials", live: meta?.catalyst_provider === "clinicaltrials" },
    { label: "Prices", live: meta?.market_provider === "twelve_data" },
    { label: "Analysts", live: meta?.analyst_provider === "fmp" },
    { label: "News", live: meta?.news_provider === "finnhub" },
  ];

  return (
    <div className="flex h-screen w-screen overflow-hidden text-on-surface">
      {/* Sidebar */}
      <nav className="fixed left-0 top-0 z-50 flex h-full w-64 flex-col border-r border-outline-variant bg-surface-container-low">
        <div className="flex items-center gap-2 border-b border-outline-variant p-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-sm border border-outline-variant bg-surface-container-highest">
            <Icon name="biotech" className="text-primary" />
          </div>
          <div>
            <h1 className="font-display-ticker text-sm font-semibold leading-tight text-primary">
              ValoreaX
            </h1>
            <div className="font-data-sm text-data-sm text-on-surface-variant">
              Terminal · {meta?.provider === "sec_edgar" ? "live" : "sample"}
            </div>
          </div>
        </div>

        <div className="flex flex-1 flex-col overflow-y-auto py-2">
          <div className="mb-4 flex flex-col gap-1 px-2">
            {NAV.map((n) => (
              <button
                key={n.tab}
                onClick={() => setTab(n.tab)}
                className={`flex items-center gap-2 rounded-sm px-4 py-1.5 font-body-main text-body-main transition-colors ${
                  tab === n.tab
                    ? "bg-secondary-container text-on-secondary-container"
                    : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
                }`}
              >
                <Icon name={n.icon} size="sm" />
                <span>{n.label}</span>
              </button>
            ))}
          </div>

          <div className="mb-2 flex items-center justify-between border-y border-outline-variant bg-surface-container-highest px-4 py-1">
            <span className="font-label-caps text-label-caps uppercase text-on-surface-variant">
              Watchlist
            </span>
          </div>

          <TickerSearch meta={meta} activeTicker={ticker} onSelect={setTicker} />
        </div>
      </nav>

      {/* Top bar */}
      <header className="fixed left-64 right-0 top-0 z-40 flex h-8 items-center justify-between border-b border-outline-variant bg-surface-container-highest px-4 font-data-tabular text-data-tabular">
        <div className="flex items-center gap-2 text-on-surface-variant">
          <Icon name="search" size="sm" />
          <span className="cursor-default opacity-70">Search ticker ⌘K</span>
        </div>
        <div className="flex items-center gap-2">
          {pills.map((p) => (
            <div
              key={p.label}
              className={`flex items-center gap-1 rounded-sm border border-outline-variant bg-surface px-1.5 py-0.5 font-data-sm text-data-sm ${
                p.live ? "text-on-surface" : "text-on-surface-variant"
              }`}
              title={p.live ? "Live data source" : "Sample / not live"}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${p.live ? "animate-pulse bg-primary" : "bg-outline"}`}
              />
              {p.label}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 text-on-surface-variant">
          <Icon name="light_mode" size="sm" className="cursor-default hover:text-primary" />
          <Icon name="account_circle" size="sm" className="cursor-default hover:text-primary" />
        </div>
      </header>

      {/* Main canvas */}
      <main className="ml-64 mt-8 mb-6 h-[calc(100vh-32px-24px)] w-full overflow-y-auto overflow-x-hidden bg-background p-6">
        <div className="mx-auto max-w-[1600px]">
          {tab === "dashboard" && <Dashboard ticker={ticker} meta={meta} />}
          {tab === "news" && <News ticker={ticker} meta={meta} />}
          {tab === "watchlist" && (
            <Watchlist
              onOpen={(t) => {
                setTicker(t);
                setTab("dashboard");
              }}
            />
          )}
          {tab === "backtest" && <Backtest ticker={ticker} />}
        </div>
      </main>

      {/* Footer */}
      <footer className="fixed bottom-0 left-64 right-0 z-40 flex h-6 items-center justify-between border-t border-outline-variant bg-surface-container-lowest px-4 font-footer-disclaimer text-footer-disclaimer text-on-surface-variant">
        <div>Educational research — not investment advice.</div>
        <div className="opacity-70">{meta?.provider === "sec_edgar" ? "SEC EDGAR · live" : "sample data"}</div>
      </footer>
    </div>
  );
}
