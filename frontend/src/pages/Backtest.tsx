import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { BacktestExplanation, InvestmentBacktest } from "../types";
import { ErrorNote, Panel, Icon } from "../components/ui";

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
const input = "mt-2 w-full rounded-xl border border-outline-variant bg-surface-container-low px-3 py-2.5 font-mono text-xs text-on-surface focus:outline-primary";

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
  const configuration = (<Panel className="backtest-config" title={<span className="flex items-center gap-2"><Icon name="tune" size="sm" />Simulation Configuration</span>}>
      {!ticker && <p className="mb-4 text-xs text-on-surface-variant">Select a company from your watchlist to begin.</p>}
      <form onSubmit={run} id="backtest-configuration" className="space-y-4">
        <label className="block text-xs font-semibold">Investment date<input className={input} type="date" required min="1900-01-01" max={end} value={start} disabled={busy} onChange={e => setStart(e.target.value)} /></label>
        <label className="block text-xs font-semibold">End date<input className={input} type="date" required min={start} max={priorDate(1)} value={end} disabled={busy} onChange={e => setEnd(e.target.value)} /></label>
        <label className="block text-xs font-semibold">Starting investment (USD)<input className={input} type="number" required min="1" max="1000000000" step="0.01" value={amount} disabled={busy} onChange={e => setAmount(e.target.value)} /></label>

      </form>
      <div className="mt-4 grid grid-cols-2 gap-2">{["SPY", "XLV"].map(symbol => <div key={symbol} className="rounded-xl border border-outline-variant bg-surface-container-low p-3"><span className="flex items-center gap-2 font-mono text-xs font-semibold"><Icon name="check_circle" size="xs" className="text-primary" />{symbol}</span><p className="mt-1 text-[10px] text-on-surface-variant">{symbol === "SPY" ? "Broad market" : "Healthcare sector"}</p></div>)}</div>
      <div className="mt-4 border-t border-outline-variant pt-4">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-primary" checked={explain} disabled={busy} onChange={e => setExplain(e.target.checked)} />Explain this result with Plutus</label>
        {explain && <>
          <label className="mt-3 block text-sm">Optional question about the result<input className={input} type="text" maxLength={1000} placeholder="e.g. What does the drawdown say about the holding period?" value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} /></label>
          <p className="mt-2 text-xs text-on-surface-variant">Plutus describes what the finished simulation shows and looks up headlines published around each detected trough and crest to explain them. Where no coverage exists it may fall back on its training data, clearly marked unverified. Not a forecast.</p>
        </>}
      </div>
      <div className="mt-5"><button disabled={!ticker || busy} type="submit" form="backtest-configuration" className="w-full rounded-xl bg-ink px-4 py-3 text-xs font-semibold text-white disabled:opacity-50">{busy ? "Loading historical prices…" : result ? "Re-run simulation" : "Run simulation"}</button></div>
      <p className="mt-4 text-xs text-on-surface-variant">Buy and hold · Up to 15 years per run · Completed daily closes · Dividends, fees, and taxes excluded</p>
    </Panel>);
  function reset() {
    generation.current++; setResult(null); setError(null); setBusy(false);
    setStart(priorDate(366)); setEnd(priorDate(1)); setAmount("10000"); setQuestion(""); setExplain(false);
  }
  return <div className="backtest-page space-y-6">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div className="min-w-0 space-y-2">
        <p className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">Portfolio Engine / Historical Simulations / <span className="text-primary">{ticker ?? "Select ticker"} Buy &amp; Hold</span></p>
        <h1 className="text-2xl font-semibold tracking-tight lg:text-3xl">Historical Investment Simulator <span className="font-normal text-on-surface-variant">{ticker ? `· ${ticker}` : ""}</span></h1>
        <p className="max-w-3xl text-sm text-on-surface-variant">Compare buy-and-hold capital allocations against SPY and XLV with daily closes and drawdown analytics.</p>
      </div>
      <div className="flex gap-2">
        <button disabled={!result || busy} onClick={() => result && downloadBacktest(result)} className="flex items-center gap-2 rounded-xl border border-outline-variant bg-surface px-3 py-2 text-xs font-medium disabled:opacity-40"><Icon name="file_download" size="xs" />Export CSV</button>
        <button disabled={busy} onClick={reset} className="flex items-center gap-2 rounded-xl bg-primary px-3 py-2 text-xs font-medium text-on-primary disabled:opacity-40"><Icon name="restart_alt" size="xs" />New Simulation</button>
      </div>
    </header>
    {error && <div role="alert"><ErrorNote message={error} /></div>}
    {busy && <p role="status" className="text-sm text-on-surface-variant">Retrieving stock and benchmark records for your selected period…</p>}
    {result && result.ticker === ticker ? <Results result={result} configuration={configuration} /> : <div className="grid gap-6 xl:grid-cols-12"><div className="xl:col-span-4">{configuration}</div><Panel className="xl:col-span-8" title="Portfolio Growth"><div className="flex min-h-80 flex-col items-center justify-center gap-4 text-center text-on-surface-variant"><Icon name="query_stats" className="text-primary" /><p>{busy ? "Building your historical comparison…" : "Your investment story starts here."}</p><p className="max-w-sm text-sm">Choose dates and capital, then run a simulation to compare {ticker ?? "your stock"}, SPY, and XLV.</p></div></Panel></div>}
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

function Results({ result: r, configuration }: { result: InvestmentBacktest; configuration: ReactNode }) {
  const [selected, setSelected] = useState(r.curve.length - 1);
  const [page, setPage] = useState(0);
  const row = r.curve[selected];
  const [mode, setMode] = useState<"value" | "return_pct">("value");
  const series = [
    { name: r.ticker, color: "text-primary", values: r.curve.map(p => p) },
    ...r.benchmarks.map((b, i) => ({ name: b.symbol, color: i === 0 ? "text-secondary" : "text-caution", values: r.curve.map(p => p.comparisons[b.symbol]) })),
  ];
  const summaries = [{ symbol: r.ticker, final_value: r.final_value, profit_loss: r.profit_loss, total_return: r.total_return, annualized_return: r.annualized_return, max_drawdown: r.max_drawdown }, ...r.benchmarks];
  const months = new Map<string, { start: number; end: number }>();
  r.curve.forEach((point, i) => { const key = point.date.slice(0, 7); const prior = months.get(key); months.set(key, { start: prior?.start ?? Math.max(0, i - 1), end: i }); });
  return <>
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Kpi label="Ending balance" value={money(r.final_value)} sub={`${pct(r.total_return)} return · Started ${money(r.investment)}`} />
      <Kpi label="Annualized CAGR" value={r.annualized_return === null ? "—" : pct(r.annualized_return)} sub={r.annualized_return === null ? "Requires at least one year" : "Over the actual holding period"} />
      {r.benchmarks.map(b => <Kpi key={b.symbol} label={`Return vs ${b.symbol}`} value={`${b.excess_return > 0 ? "+" : ""}${(b.excess_return * 100).toFixed(2)} pp`} color={b.excess_return < 0 ? "text-error" : "text-primary"} sub={`${b.symbol}: ${money(b.final_value)} (${pct(b.total_return)})`} />)}
      <Kpi label="Max drawdown" value={pct(r.max_drawdown)} color="text-error" sub="Largest decline from prior peak" />
      <Kpi label="Time horizon" value={`${r.trading_sessions} sessions`} sub={`${r.entry_date} → ${r.exit_date}`} />
    </div>
    <div className="grid min-w-0 gap-6 xl:grid-cols-12">
    <div className="min-w-0 xl:col-span-4">{configuration}</div>
    <Panel className="min-w-0 xl:col-span-8" title="Portfolio Growth">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-on-surface-variant">{r.entry_date} → {r.exit_date} · {r.trading_sessions} shared sessions</p>
        <div className="flex gap-2">{([['value', 'Dollar value'], ['return_pct', 'Return %']] as const).map(([value, name]) => <button key={value} aria-pressed={mode === value} onClick={() => setMode(value)} className={`rounded-full px-3 py-2 text-sm ${mode === value ? "bg-primary text-on-primary" : "bg-surface-container"}`}>{name}</button>)}</div>
      </div>
      <ComparisonChart series={series} field={mode} dates={r.curve.map(p => p.date)} selected={selected} onSelect={setSelected} />
      <label className="mt-3 block text-sm">Explore a trading session<input type="range" className="mt-2 w-full accent-primary" min="0" max={r.curve.length - 1} value={selected} onChange={e => setSelected(Number(e.target.value))} aria-valuetext={`${row.date}: ${money(row.value)}`} /></label>
      <div className="mt-3 flex flex-wrap gap-4 rounded-xl bg-surface-container p-4 text-sm" aria-live="polite"><strong>{row.date}</strong>{series.map((s, i) => <span key={i} className={s.color}>{s.name}: {money(s.values[selected].value)} ({pct(s.values[selected].return_pct)})</span>)}</div>
    </Panel>
    <Panel className="backtest-drawdown xl:col-span-12" title="Decline from Prior Peak (Drawdown)">
      <ComparisonChart series={series} field="drawdown" dates={r.curve.map(p => p.date)} selected={selected} onSelect={setSelected} />
      <div className="mt-3 flex flex-wrap gap-4 text-sm"><span>{row.date}</span>{series.map((s, i) => <span key={i} className={s.color}>{s.name}: {pct(s.values[selected].drawdown)}</span>)}</div>
      <p className="mt-3 text-xs text-on-surface-variant">Peaks begin at the investment date. Zero means the investment is at its highest value so far in this period.</p>
    </Panel>
    <Panel className="min-w-0 xl:col-span-8" title="Comparative Risk–Return Summary">
      <div className="overflow-x-auto"><table className="w-full min-w-[600px] text-left text-sm"><thead><tr className="border-b border-outline-variant">{['Investment', 'Ending value', 'Profit / loss', 'Return', 'CAGR', 'Max drawdown'].map(h => <th key={h} className="py-3 pr-4">{h}</th>)}</tr></thead><tbody>{summaries.map((s, i) => <tr key={i} className="border-b border-outline-variant/40"><th className={`py-4 pr-4 ${series[i].color}`}>{s.symbol}</th><td>{money(s.final_value)}</td><td>{money(s.profit_loss)}</td><td>{pct(s.total_return)}</td><td>{s.annualized_return === null ? "—" : pct(s.annualized_return)}</td><td>{pct(s.max_drawdown)}</td></tr>)}</tbody></table></div>
      <p className="mt-3 text-xs text-on-surface-variant">Same starting capital and holding period for each investment. CAGR requires at least one year. SPY provides the broad-market comparison; XLV provides the healthcare-sector comparison.</p>
    </Panel>
    <Panel className="min-w-0 xl:col-span-4" title="Monthly Returns Matrix">
      <div className="max-h-80 overflow-auto"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-surface"><tr><th className="p-3">Month</th>{series.map((s, i) => <th key={i} className={`p-3 ${s.color}`}>{s.name}</th>)}</tr></thead><tbody>{[...months].reverse().map(([month, range]) => <tr key={month}><th className="p-3 font-normal">{month}</th>{series.map((s, i) => { const value = s.values[range.end].value / s.values[range.start].value - 1; return <td key={i} className="p-1"><div className={`rounded-md p-3 font-mono ${value > 0 ? "bg-primary/10 text-primary" : value < 0 ? "bg-error/10 text-error" : "bg-surface-container"}`}>{value > 0 ? "+" : ""}{pct(value)}</div></td>; })}</tr>)}</tbody></table></div>
      <p className="mt-3 text-xs text-on-surface-variant">First and last months may be partial. Each month starts at the previous included month-end close; the first starts at entry.</p>
    </Panel>
    {r.explanation && <div className="xl:col-span-12"><PlutusExplanation explanation={r.explanation} /></div>}
    <Panel className="xl:col-span-12" title="Moving Average Technical Posture">
      <div className="grid gap-4 sm:grid-cols-2">
        {([['Before investing', r.entry_outlook], ['At the end', r.exit_outlook]] as const).map(([title, o]) => <div key={title} className="rounded-md border border-outline-variant p-4"><p className="text-sm text-on-surface-variant">{title} · {o.as_of ?? "No earlier history"}</p><p className="mt-2 text-xl font-semibold">{label(o.label)}</p><p className="mt-2 text-sm">20-session average: {o.sma20 === null ? "—" : money(o.sma20)} · 60-session average: {o.sma60 === null ? "—" : money(o.sma60)}</p></div>)}
      </div>
      <p className="mt-4 text-sm leading-relaxed text-on-surface-variant">{r.outlook_methodology}</p>
    </Panel>
    <details className="rounded-3xl border border-outline-variant bg-surface xl:col-span-12"><summary className="cursor-pointer px-6 py-4 text-sm font-semibold">Daily Historical Records · {r.trading_sessions} sessions</summary><Panel title="Daily historical records">
      <button onClick={() => downloadBacktest(r)} className="mb-3 text-sm text-primary hover:underline">Download all daily comparisons (CSV)</button>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b border-outline-variant"><th className="py-2">Date</th><th>Adjusted close</th><th>Portfolio</th><th>SPY</th><th>XLV</th><th>Return</th><th>Trend at close</th></tr></thead><tbody>{r.curve.slice(page * 50, (page + 1) * 50).map(point => <tr key={point.date} className="border-b border-outline-variant/40"><td className="py-2 pr-3">{point.date}</td><td>{money(point.close)}</td><td>{money(point.value)}</td><td>{money(point.comparisons.SPY.value)}</td><td>{money(point.comparisons.XLV.value)}</td><td>{pct(point.return_pct)}</td><td>{label(point.outlook)}</td></tr>)}</tbody></table></div>
      <div className="mt-4 flex items-center justify-between text-sm"><button className="text-primary disabled:opacity-40" disabled={page === 0} onClick={() => setPage(n => n - 1)}>Previous</button><span>Page {page + 1} of {Math.ceil(r.curve.length / 50)}</span><button className="text-primary disabled:opacity-40" disabled={(page + 1) * 50 >= r.curve.length} onClick={() => setPage(n => n + 1)}>Next</button></div>
    </Panel>
    </details>
    <Panel className="xl:col-span-12" title="Method and Data Coverage">
      <p className="text-sm leading-relaxed text-on-surface-variant">{r.methodology}</p>
      {!!r.warnings.length && <ul className="mt-3 list-inside list-disc space-y-1 text-sm">{r.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
      <p className="mt-3 text-sm text-on-surface-variant">Source: Twelve Data · USD · Split-adjusted prices, excluding dividend returns.</p>
      {r.retrieval.map(source => <p key={source.symbol} className="mt-1 text-sm text-on-surface-variant">{source.symbol}: retrieved {new Date(source.fetched_at).toLocaleString()}{source.cached ? " (cached)" : ""}</p>)}
    </Panel>
    </div>
  </>;
}

function ComparisonChart({ series, field, dates, selected, onSelect }: {
  series: Array<{ name: string; color: string; values: Array<{ value: number; return_pct: number; drawdown: number }> }>;
  field: "value" | "return_pct" | "drawdown"; dates: string[]; selected: number; onSelect: (index: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const index = hover ?? selected;
  const values = series.flatMap(s => s.values.map(p => p[field]));
  const low = field === "value" ? Math.min(...values) : Math.min(0, ...values), high = Math.max(0, ...values);
  const pad = Math.max((high - low) * .08, field === "value" ? 1 : .005);
  const min = low - pad, max = high + pad;
  const x = (i: number) => 80 + i / Math.max(1, dates.length - 1) * 890;
  const bottom = field === "drawdown" ? 150 : 290;
  const y = (v: number) => bottom - (v - min) / (max - min) * (bottom - 25);
  const format = (v: number) => field === "value" ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact" }).format(v) : pct(v);
  return <>
    <div className="mb-3 flex flex-wrap gap-5 text-sm">{series.map((s, i) => <span key={i} className={s.color}>{i === 0 ? "━━" : i === 1 ? "┄┄" : "····"} {s.name}</span>)}</div>
    <svg viewBox={`0 0 1000 ${bottom + 40}`} role="img" aria-label={`${field === "drawdown" ? "Drawdown" : field === "value" ? "Investment value" : "Cumulative return"}: ${series.map(s => s.name).join(', ')}`} className="w-full touch-pan-y" onPointerMove={event => {
      const bounds = event.currentTarget.getBoundingClientRect();
      setHover(Math.max(0, Math.min(dates.length - 1, Math.round(((event.clientX - bounds.left) / bounds.width * 1000 - 80) / 890 * (dates.length - 1)))));
    }} onPointerLeave={() => setHover(null)} onClick={() => { if (hover != null) onSelect(hover); }}>
      {[0,1,2,3,4].map(i => { const v = min + (max - min) * i / 4; return <g key={i}><line x1="80" x2="970" y1={y(v)} y2={y(v)} stroke="currentColor" opacity=".12"/><text x="70" y={y(v)+4} textAnchor="end" fill="currentColor" fontSize="12">{format(v)}</text></g>; })}
      {min <= 0 && <line x1="80" x2="970" y1={y(0)} y2={y(0)} stroke="currentColor" opacity=".3" />}
      {series.map((s, i) => <g key={i} className={s.color}><path d={s.values.map((p, j) => `${j ? 'L' : 'M'}${x(j)},${y(p[field])}`).join(' ')} stroke="currentColor" fill="none" strokeWidth="2.5" strokeDasharray={i === 1 ? "8 5" : i === 2 ? "2 4" : undefined}/><circle cx={x(index)} cy={y(s.values[index][field])} r="4" fill="currentColor"/></g>)}
      <line x1={x(index)} x2={x(index)} y1="25" y2={bottom} stroke="currentColor" opacity=".4"/>
      <text x="80" y={bottom + 30} fontSize="12" fill="currentColor">{dates[0]}</text><text x="970" y={bottom + 30} textAnchor="end" fontSize="12" fill="currentColor">{dates[dates.length - 1]}</text>
    </svg>
  </>;
}

function Kpi({ label, value, sub, color = "text-on-surface" }: { label: string; value: string; sub: string; color?: string }) {
  return <div className="min-w-0 rounded-2xl border border-outline-variant/70 bg-surface p-4 shadow-sm"><p className="text-[10px] font-medium uppercase tracking-wide text-on-surface-variant">{label}</p><p className={`mt-2 font-mono text-lg font-semibold tabular-nums ${color}`}>{value}</p><p className="mt-2 text-[10px] leading-relaxed text-on-surface-variant">{sub}</p></div>;
}

function downloadBacktest(r: InvestmentBacktest) {
  const symbols = [r.ticker, ...r.benchmarks.map(b => b.symbol)];
  const rows = [["Date", ...symbols.flatMap(s => [`${s} value`, `${s} return`, `${s} drawdown`])], ...r.curve.map(p => [p.date, ...[p, ...r.benchmarks.map(b => p.comparisons[b.symbol])].flatMap(v => [v.value, v.return_pct, v.drawdown])])];
  const url = URL.createObjectURL(new Blob([rows.map(row => row.join(",")).join("\n")], { type: "text/csv" }));
  const link = document.createElement("a"); link.href = url; link.download = `${r.ticker}-SPY-XLV-backtest.csv`; link.click(); URL.revokeObjectURL(url);
}
