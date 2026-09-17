import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./auth/supabase";
import { api } from "./api/client";
import type { Meta } from "./types";
import TickerSearch from "./components/TickerSearch";
import { ErrorNote, Icon } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Backtest from "./pages/Backtest";
import Watchlist from "./pages/Watchlist";
import News from "./pages/News";

type Tab = "clinical" | "financials" | "dashboard" | "news" | "watchlist" | "backtest";

const NAV: Array<{ tab: Tab; label: string; icon: string }> = [
  { tab: "dashboard", label: "Dashboard", icon: "grid_view" },
  { tab: "clinical", label: "Clinical Pipeline", icon: "science" },
  { tab: "financials", label: "Valuation & Financials", icon: "finance_mode" },
  { tab: "news", label: "News Intelligence", icon: "hub" },
  { tab: "watchlist", label: "Watchlist", icon: "pie_chart" },
  { tab: "backtest", label: "Backtest", icon: "query_stats" },
];

export default function App({ session }: { session: Session }) {
  const [darkMode, setDarkMode] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
    try { localStorage.setItem("valoreax-theme", darkMode ? "dark" : "light"); } catch { /* Theme still works without storage. */ }
  }, [darkMode]);
  const [search, setSearch] = useState("");
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [ticker, setTicker] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("dashboard");

  const [navigation, setNavigation] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshWarnings, setRefreshWarnings] = useState<string[]>([]);
  const [loadedNavigation, setLoadedNavigation] = useState(0);

  function navigate(next: Tab, selected = ticker) {
    if (next === tab && selected === ticker) return;
    setTab(next);
    setTicker(selected);
    setNavigation(value => value + 1);
  }

  useEffect(() => {
    let active = true;
    setRefreshing(true);
    setRefreshWarnings([]);
    api.refreshNavigation(tab === "clinical" || tab === "financials" ? "dashboard" : tab, ticker).then(result => {
      if (active) setRefreshWarnings(result.warnings);
    }).catch(error => {
      if (active) setRefreshWarnings([`Unable to refresh sources: ${error.message}. Showing stored data.`]);
    }).finally(() => {
      if (active) { setRefreshing(false); setLoadedNavigation(value => value + 1); }
    });
    return () => { active = false; };
  }, [tab, ticker, navigation]);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  async function signOut() {
    if (!supabase) return;
    setSigningOut(true); setSignOutError(null);
    try {
      const { error } = await supabase.auth.signOut({ scope: "local" });
      if (error) throw error;
    } catch {
      setSignOutError("Unable to sign out. Please retry.");
    } finally { setSigningOut(false); }
  }

  const pills: Array<{ label: string; live: boolean }> = [
    { label: "SEC", live: meta?.provider === "sec_edgar" },
    { label: "Trials", live: meta?.catalyst_provider === "clinicaltrials" },
    { label: "Prices", live: meta?.market_provider === "twelve_data" },
    { label: "Analysts", live: meta?.analyst_provider === "fmp" },
    { label: "News", live: meta?.news_provider === "finnhub" },
  ];

  async function searchTicker(event: React.FormEvent) {
    event.preventDefault();
    const selected = search.trim().toUpperCase();
    if (!selected || searching) return;
    setSearching(true); setSearchError(null);
    try {
      const known = await api.listCompanies();
      if (!known.companies.some(company => company.ticker === selected)) await api.ingestCompany(selected);
      navigate("dashboard", selected); setSearch("");
    } catch (error) { setSearchError(error instanceof Error ? error.message : "Unable to load ticker."); }
    finally { setSearching(false); }
  }

  return (
    <div className="min-h-screen bg-background text-on-surface">
      <aside className="app-sidebar fixed left-0 top-0 z-50 flex h-screen flex-col justify-between bg-surface-container-low p-5">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mb-9 flex items-center gap-3 px-2 pt-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-ink text-white"><Icon name="nature" size="base" /></div>
            <div><h1 className="text-lg font-semibold tracking-tight">ValoreaX</h1><p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Biotech Intelligence</p></div>
          </div>
          <nav className="flex flex-col gap-1" aria-label="Main navigation">
            {NAV.map(n => <button key={n.tab} onClick={() => navigate(n.tab)} aria-current={tab === n.tab ? "page" : undefined}
              className={`flex items-center gap-3 rounded-full px-5 py-3 text-left text-sm ${tab === n.tab ? "bg-surface-container-highest font-semibold shadow-sm" : "text-on-surface-variant hover:bg-surface-container"}`}>
              <Icon name={n.icon} size="base" />{n.label}
            </button>)}
          </nav>
          <div className="ticker-list mt-8"><p className="mb-3 px-4 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Your research universe</p>
            <TickerSearch meta={meta} activeTicker={ticker} onSelect={selected => navigate(tab, selected)} refreshKey={loadedNavigation} />
          </div>
        </div>
        <div className="sidebar-bottom mt-5 space-y-5">
          <button onClick={() => navigate("watchlist")} className="w-full rounded-2xl bg-surface-container p-4 text-left">
            <span className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant"><span className="h-2 w-2 rounded-full bg-primary" />Portfolio watch</span>
            <p className="mt-2 text-sm font-medium">Your companies. In focus.</p><p className="mt-1 text-xs text-on-surface-variant">Prices · Clinical catalysts · Signals</p>
          </button>
          <div className="flex items-center gap-3 px-1"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink text-white"><Icon name="person" /></div>
            <div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold" title={session.user.email}>{session.user.email}</p><button onClick={signOut} disabled={signingOut} className="mt-1 text-xs text-on-surface-variant hover:text-error">{signingOut ? "Signing out…" : "Sign out"}</button></div>
          </div>{signOutError && <ErrorNote message={signOutError} />}
        </div>
      </aside>
      <header className="app-header fixed right-0 top-0 z-40 flex h-20 items-center justify-between gap-4 bg-surface-container-low/90 px-7 backdrop-blur-xl">
        <form onSubmit={searchTicker} className="flex min-w-0 flex-1 max-w-xl items-center gap-3 rounded-full bg-surface px-5 py-3 shadow-sm">
          <Icon name="search" /><input aria-label="Search company ticker" className="min-w-0 flex-1 bg-transparent text-sm outline-none" placeholder="Search a company ticker…" value={search} onChange={event => setSearch(event.target.value)} />
          <button disabled={searching} type="submit" aria-label="Load ticker" className="rounded-full bg-surface-container px-2 py-1 text-xs">{searching ? "Loading…" : "↵"}</button>
        </form>
        <div className="ml-auto flex shrink-0 items-center gap-3">
        <button className="sm:hidden" onClick={signOut} disabled={signingOut} aria-label="Sign out"><Icon name="logout" /></button>
        <div className="hidden items-center gap-3 md:flex"><span className="flex h-10 items-center rounded-full bg-surface px-4 text-xs shadow-sm"><span className="mr-2 inline-block h-2 w-2 rounded-full bg-blue-500" />Plutus · Gemini</span><span className="flex h-10 items-center rounded-full bg-surface-container px-3 font-mono text-xs">{ticker ?? "Select ticker"}</span></div>
        <button type="button" onClick={() => setDarkMode(value => !value)} aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"} title={darkMode ? "Switch to light mode" : "Switch to dark mode"} aria-pressed={darkMode} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-outline-variant bg-surface text-on-surface shadow-sm hover:bg-surface-container">
          <Icon name={darkMode ? "light_mode" : "dark_mode"} size="base" />
        </button>
        </div>
      </header>
      <main className="app-main min-h-screen px-5 pb-8 pt-28 lg:px-8">
        <div className="mx-auto max-w-[1600px] space-y-6">
          {searchError && <ErrorNote message={searchError} />}
          {refreshWarnings.map((warning, i) => <ErrorNote key={i} message={warning} />)}
          {refreshing && <p className="text-xs text-on-surface-variant">Checking for updated data…</p>}
          <div hidden={!(tab === "dashboard" || tab === "clinical" || tab === "financials")}>
            <Dashboard ticker={ticker} meta={meta} focus={tab === "clinical" || tab === "financials" ? tab : "dashboard"} />
          </div>
          <div hidden={tab !== "news"}><News ticker={ticker} meta={meta} /></div>
          <div hidden={tab !== "watchlist"}><Watchlist onOpen={selected => navigate("dashboard", selected)} /></div>
          <div hidden={tab !== "backtest"}><Backtest ticker={ticker} refreshKey={tab === "backtest" ? loadedNavigation : 0} /></div>
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-outline-variant pt-5 text-[11px] text-on-surface-variant"><p>Educational research — not investment advice.</p><div className="flex gap-3">{pills.map(p => <span key={p.label}>{p.label} · {p.live ? "Live source" : "Sample"}</span>)}</div></footer>
        </div>
      </main>
    </div>
  );
}
