import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { BacktestExplanation, InvestmentBacktest } from "../types";
import { ErrorNote, Panel, Stat } from "../components/ui";

const money = (value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
const pct = (value: number) => `${(value * 100).toFixed(2)}%`;
const label = (value: string) => value === "insufficient_history" ? "Insufficient history" : value[0].toUpperCase() + value.slice(1);
function priorDate(days: number) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const value = (type: string) => parts.find(part => part.type === type)!.value;
  const date = new Date(`${value("year")}-${value("month")}-${value("day")}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}
const input = "mt-2 w-full rounded-md border border-outline-variant bg-background px-3 py-2 text-base text-on-surface focus:outline-primary";

export default function Backtest({ ticker, refreshKey = 0 }: { ticker: string | null; refreshKey?: number }) {
  const [start, setStart] = useState(() => priorDate(366));
  const [end, setEnd] = useState(() => priorDate(1));
  const [amount, setAmount] = useState("10000");
  const [explain, setExplain] = useState(false);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<InvestmentBacktest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    generation.current++; setResult(null); setError(null); setBusy(false);
    return () => { generation.current++; };
  }, [ticker]);
  useEffect(() => {
    if (refreshKey && result) void run();
  }, [refreshKey]);
  async function run(event?: FormEvent) {
    event?.preventDefault();
    if (!ticker || busy) return;
    if (start >= end) { setError("Start date must be before end date."); return; }
    const requestId = ++generation.current;
    setBusy(true); setError(null); setResult(null);
    try {
      const data = await api.simulateInvestment(ticker, {
        start_date: start, end_date: end, investment: Number(amount),
        explain, question: explain ? question.trim() : "",
      });
      if (generation.current === requestId) setResult(data);
    } catch (err) {
      const details = err instanceof ApiError && err.details && typeof err.details === "object"
        ? Object.values(err.details).flat().filter(value => typeof value === "string").join(" ") : "";
      if (generation.current === requestId) setError(details || (err instanceof Error ? err.message : "Unable to run simulation."));
    } finally { if (generation.current === requestId) setBusy(false); }
  }
  return <div className="space-y-5">
    <div><h1 className="text-2xl font-semibold">Historical investment simulator{ticker ? ` · ${ticker}` : ""}</h1><p className="mt-2 text-base text-on-surface-variant">Choose when you invested and how much. See how a buy-and-hold investment performed.</p></div>
    <Panel title="Investment setup">
      {!ticker && <p className="mb-4 text-sm text-on-surface-variant">Select a company from your watchlist to begin.</p>}
      <form onSubmit={run} className="grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <label className="text-sm">Investment date<input className={input} type="date" required min="1900-01-01" max={end} value={start} disabled={busy} onChange={e => setStart(e.target.value)} /></label>
        <label className="text-sm">End date<input className={input} type="date" required min={start} max={priorDate(1)} value={end} disabled={busy} onChange={e => setEnd(e.target.value)} /></label>
        <label className="text-sm">Starting investment (USD)<input className={input} type="number" required min="1" max="1000000000" step="0.01" value={amount} disabled={busy} onChange={e => setAmount(e.target.value)} /></label>
        <button disabled={!ticker || busy} type="submit" className="rounded-md bg-primary px-4 py-2.5 text-base font-semibold text-on-primary disabled:opacity-50">{busy ? "Loading historical prices…" : "Run simulation"}</button>
      </form>
      <div className="mt-4 border-t border-outline-variant pt-4">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-primary" checked={explain} disabled={busy} onChange={e => setExplain(e.target.checked)} />Explain this result with Plutus</label>
        {explain && <>
          <label className="mt-3 block text-sm">Optional question about the result<input className={input} type="text" maxLength={1000} placeholder="e.g. What does the drawdown say about the holding period?" value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} /></label>
          <p className="mt-2 text-sm text-on-surface-variant">Plutus describes what the finished simulation shows and looks up headlines published around each detected trough and crest to explain them. Where no coverage exists it may fall back on its training data, clearly marked unverified. Not a forecast.</p>
        </>}
      </div>
      <p className="mt-4 text-sm text-on-surface-variant">Buy and hold · Up to 15 years per run · Completed daily closes · Dividends, fees, and taxes excluded</p>
    </Panel>
    {error && <div role="alert"><ErrorNote message={error} /></div>}
    {busy && <p role="status" className="text-sm text-on-surface-variant">Retrieving stock and benchmark records for your selected period…</p>}
    {result && result.ticker === ticker && <Results result={result} />}
  </div>;
}

function PlutusExplanation({ explanation: e }: { explanation: BacktestExplanation }) {
  if (e.status !== "ready") {
    return <Panel title="Plutus explanation">
      {e.status === "error" ? <ErrorNote message={e.message} />
        : <p className="text-sm text-on-surface-variant">{e.message} The simulation results below are unaffected.</p>}
    </Panel>;
  }
  const sections = [
    ["What the result shows", e.observations],
    ["What could mislead", e.cautions],
    ["Tensions in the figures", e.tensions],
  ] as const;
  return <Panel title="Plutus explanation">
    <p className="mb-2 text-sm text-on-surface-variant">{e.model} · {new Date(e.generated_at).toLocaleString()}{e.cached ? " · Cached" : ""}</p>
    <p className="text-base leading-relaxed">{e.summary}</p>
    <div className="mt-5 grid gap-5 lg:grid-cols-3">
      {sections.map(([title, points]) => points.length > 0 && <div key={title}>
        <h3 className="mb-2 text-sm font-semibold">{title}</h3>
        <ul className="space-y-2 text-sm">{points.map((p, i) => <li key={i}>{p.text}<span className="ml-1 text-on-surface-variant">{p.evidence_ids.map(id => `[${id}]`).join(" ")}</span></li>)}</ul>
      </div>)}
    </div>
    {e.context.length > 0 && <div className="mt-5 rounded-md border border-outline-variant bg-background p-4">
      <h3 className="text-sm font-semibold">Possible reasons for the moves</h3>
      <p className="mt-1 text-sm text-on-surface-variant">Entries marked <strong>Sourced</strong> cite headlines published around that move — open them to check. <strong>Unverified</strong> entries come from the model's training data with no source, and may be wrong or mis-dated. Confidence grades how well the event explains the move, not whether it happened.</p>
      <ul className="mt-3 space-y-3 text-sm">{e.context.map((item, i) => {
        const articles = item.evidence_ids.flatMap(id => {
          const record = e.evidence.find(r => r.id === id);
          const data = record?.data as { articles?: Array<{ headline: string; source: string | null; url: string | null }> } | undefined;
          return (data?.articles ?? []).map(a => ({ ...a, id }));
        });
        return <li key={i} className={`rounded-md p-3 ${item.sourced ? "bg-surface-container-low" : "border border-dashed border-outline-variant"}`}>
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="rounded bg-surface-container px-2 py-0.5 font-mono text-xs">{item.approximate_date}</span>
            <span className={`rounded px-2 py-0.5 text-xs font-semibold ${item.sourced ? "bg-primary/15 text-primary" : "bg-error/10 text-error"}`}>{item.sourced ? "Sourced" : "Unverified"}</span>
            <span className="rounded bg-surface-container px-2 py-0.5 text-xs text-on-surface-variant">{item.confidence} confidence</span>
          </div>
          <p className="mt-2">{item.text}</p>
          {articles.length > 0 && <ul className="mt-2 space-y-1 text-xs text-on-surface-variant">{articles.slice(0, 4).map((a, j) => <li key={j}>
            {a.url ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{a.headline}</a> : a.headline}
            {a.source ? ` · ${a.source}` : ""}
          </li>)}</ul>}
        </li>;
      })}</ul>
    </div>}
    {e.limitations.length > 0 && <div className="mt-5">
      <h3 className="text-sm font-semibold">What this cannot tell you</h3>
      <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-on-surface-variant">{e.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </div>}
    <details className="mt-5 border-t border-outline-variant pt-3">
      <summary className="cursor-pointer text-sm text-primary">Inspect evidence used ({e.evidence.length} records)</summary>
      <div className="mt-3 space-y-2">{e.evidence.map(item => <details key={item.id} className="rounded border border-outline-variant p-2">
        <summary className="cursor-pointer text-sm">[{item.id}] {item.label}</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-on-surface-variant">{JSON.stringify(item.data, null, 2)}</pre>
      </details>)}</div>
    </details>
    <p className="mt-4 text-sm text-on-surface-variant">AI-generated description of a completed simulation. Findings are derived from the cited evidence; reasons for the moves are cited to published headlines where news coverage exists, and marked unverified where it does not. Not a forecast and not a recommendation. Past results do not indicate future performance.</p>
  </Panel>;
}

function Results({ result: r }: { result: InvestmentBacktest }) {
  const [selected, setSelected] = useState(r.curve.length - 1);
  const [page, setPage] = useState(0);
  const row = r.curve[selected];
  const values = r.curve.flatMap(point => [point.value, point.benchmark_value]);
  const low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max((high - low) * .12, high * .01, 1);
  const min = low - padding, max = high + padding;
  const x = (index: number) => 85 + index / (r.curve.length - 1) * 895;
  const y = (value: number) => 275 - (value - min) / (max - min) * 250;
  const path = (key: "value" | "benchmark_value") => r.curve.map((point, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(point[key]).toFixed(2)}`).join(" ");
  return <>
    {r.explanation && <PlutusExplanation explanation={r.explanation} />}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Stat label="Ending balance" value={money(r.final_value)} sub={`Started with ${money(r.investment)}`} />
      <Stat label="Profit / loss" value={money(r.profit_loss)} sub={`${pct(r.total_return)} price return`} />
      <Stat label={`${r.benchmark} ending balance`} value={money(r.benchmark_final_value)} sub={`${pct(r.benchmark_return)} benchmark return`} />
      <Stat label="Maximum drawdown" value={pct(r.max_drawdown)} sub="Largest decline from a previous peak" />
    </div>
    <Panel title="Portfolio value over time">
      <div className="mb-4 flex flex-wrap gap-5 text-sm"><span className="text-primary">━━ {r.ticker}</span><span className="text-on-surface-variant">┄┄ {r.benchmark}</span><span>{r.entry_date} → {r.exit_date} · {r.trading_sessions} sessions</span></div>
      <svg viewBox="0 0 1000 310" role="img" aria-label={`${r.ticker} portfolio value compared with ${r.benchmark}`} className="w-full" onPointerMove={event => {
        const bounds = event.currentTarget.getBoundingClientRect();
        const index = Math.round((((event.clientX - bounds.left) / bounds.width) * 1000 - 85) / 895 * (r.curve.length - 1));
        setSelected(Math.min(r.curve.length - 1, Math.max(0, index)));
      }}>
        {[0, 1, 2, 3, 4].map(i => { const value = min + (max - min) * i / 4; return <g key={i}><line x1="85" x2="980" y1={y(value)} y2={y(value)} stroke="currentColor" opacity=".12" /><text x="75" y={y(value) + 4} textAnchor="end" fill="currentColor" fontSize="12">{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(value)}</text></g>; })}
        <path d={path("benchmark_value")} fill="none" stroke="currentColor" strokeDasharray="6 4" strokeWidth="2" opacity=".6" />
        <path d={path("value")} fill="none" className="stroke-primary" strokeWidth="2.5" />
        <line x1={x(selected)} x2={x(selected)} y1="25" y2="275" stroke="currentColor" opacity=".3" />
        <circle cx={x(selected)} cy={y(row.value)} r="4" className="fill-primary" />
        <text x="85" y="302" fill="currentColor" fontSize="12">{r.entry_date}</text><text x="980" y="302" textAnchor="end" fill="currentColor" fontSize="12">{r.exit_date}</text>
      </svg>
      <label className="mt-2 block text-sm">Explore a trading session<input type="range" className="mt-2 w-full accent-primary" min="0" max={r.curve.length - 1} value={selected} onChange={e => setSelected(Number(e.target.value))} aria-valuetext={`${row.date}: ${money(row.value)}`} /></label>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 rounded-md bg-background p-3 text-sm" aria-live="polite"><span>{row.date}</span><span>{r.ticker}: {money(row.value)}</span><span>{r.benchmark}: {money(row.benchmark_value)}</span><span>Trend at close: {label(row.outlook)}</span></div>
    </Panel>
    <Panel title="Historical trend assessment">
      <div className="grid gap-4 sm:grid-cols-2">
        {([['Before investing', r.entry_outlook], ['At the end', r.exit_outlook]] as const).map(([title, o]) => <div key={title} className="rounded-md border border-outline-variant p-4"><p className="text-sm text-on-surface-variant">{title} · {o.as_of ?? "No earlier history"}</p><p className="mt-2 text-xl font-semibold">{label(o.label)}</p><p className="mt-2 text-sm">20-session average: {o.sma20 === null ? "—" : money(o.sma20)} · 60-session average: {o.sma60 === null ? "—" : money(o.sma60)}</p></div>)}
      </div>
      <p className="mt-4 text-sm leading-relaxed text-on-surface-variant">{r.outlook_methodology}</p>
    </Panel>
    <Panel title="Performance details">
      <div className="grid gap-3 sm:grid-cols-3"><Stat label="Annualized price return" value={r.annualized_return === null ? "Not annualized" : pct(r.annualized_return)} sub={r.annualized_return === null ? "Requires at least one year" : "CAGR over actual holding period"} /><Stat label="Return vs benchmark" value={`${(r.excess_return * 100).toFixed(2)} pp`} sub="Difference in percentage points" /><Stat label="Adjusted entry / exit close" value={`${money(r.entry_close)} / ${money(r.exit_close)}`} /></div>
    </Panel>
    <Panel title="Daily historical records">
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b border-outline-variant"><th className="py-2">Date</th><th>Adjusted close</th><th>Portfolio</th><th>{r.benchmark}</th><th>Return</th><th>Trend at close</th></tr></thead><tbody>{r.curve.slice(page * 50, (page + 1) * 50).map(point => <tr key={point.date} className="border-b border-outline-variant/40"><td className="py-2 pr-3">{point.date}</td><td>{money(point.close)}</td><td>{money(point.value)}</td><td>{money(point.benchmark_value)}</td><td>{pct(point.return_pct)}</td><td>{label(point.outlook)}</td></tr>)}</tbody></table></div>
      <div className="mt-4 flex items-center justify-between text-sm"><button className="text-primary disabled:opacity-40" disabled={page === 0} onClick={() => setPage(n => n - 1)}>Previous</button><span>Page {page + 1} of {Math.ceil(r.curve.length / 50)}</span><button className="text-primary disabled:opacity-40" disabled={(page + 1) * 50 >= r.curve.length} onClick={() => setPage(n => n + 1)}>Next</button></div>
    </Panel>
    <Panel title="Method and data coverage">
      <p className="text-sm leading-relaxed text-on-surface-variant">{r.methodology}</p>
      {!!r.warnings.length && <ul className="mt-3 list-inside list-disc space-y-1 text-sm">{r.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
      <p className="mt-3 text-sm text-on-surface-variant">Source: Twelve Data · USD · Split-adjusted prices, excluding dividend returns.</p>
      {r.retrieval.map(source => <p key={source.symbol} className="mt-1 text-sm text-on-surface-variant">{source.symbol}: retrieved {new Date(source.fetched_at).toLocaleString()}{source.cached ? " (cached)" : ""}</p>)}
    </Panel>
  </>;
}
