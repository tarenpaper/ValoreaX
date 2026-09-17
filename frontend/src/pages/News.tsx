import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type {
  CatalystMatrixRow,
  Meta,
  NewsArticle,
  NewsMarker,
  NewsView,
  SectorSentiment,
  TrendingTopic,
} from "../types";
import { formatPct } from "../format";
import { ErrorNote, Icon, Spinner, TerminalPanel } from "../components/ui";
import SignalPanel from "../components/SignalPanel";

const IMPACTS = ["critical", "high", "medium", "low"];

const IMPACT_STYLE: Record<string, string> = {
  critical: "border-error/30 bg-error-container/20 text-error",
  high: "border-tertiary-fixed-dim/40 bg-tertiary-fixed-dim/10 text-tertiary-fixed-dim",
  medium: "border-outline-variant bg-surface-variant text-on-surface-variant",
  low: "border-outline-variant bg-surface-container text-on-surface-variant",
};

const SENTIMENT: Record<string, { text: string; bar: string; icon: string; word: string }> = {
  bullish: { text: "text-primary", bar: "bg-primary", icon: "trending_up", word: "Bullish" },
  bearish: { text: "text-error", bar: "bg-error", icon: "trending_down", word: "Bearish" },
  neutral: { text: "text-on-surface-variant", bar: "bg-outline-variant", icon: "remove", word: "Neutral" },
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function News({ ticker, meta }: { ticker: string | null; meta: Meta | null }) {
  const [view, setView] = useState<NewsView | null>(null);
  const [loading, setLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [impactFilter, setImpactFilter] = useState<Set<string>>(new Set(IMPACTS));
  const [clinicalOnly, setClinicalOnly] = useState(false);

  const canIngest = meta?.news_provider === "finnhub" || meta?.news_provider === "mock";

  const load = useCallback(async (t: string) => {
    setLoading(true);
    setError(null);
    try {
      setView(await api.news(t));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setView(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ticker) load(ticker);
    else setView(null);
  }, [ticker, load]);

  async function ingest() {
    if (!ticker) return;
    setIngesting(true);
    setError(null);
    try {
      setView(await api.ingestNews(ticker));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setIngesting(false);
    }
  }

  function toggleImpact(i: string) {
    setImpactFilter((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  const articles = useMemo(
    () =>
      (view?.articles ?? []).filter(
        (a) => impactFilter.has(a.impact) && (!clinicalOnly || a.is_clinical),
      ),
    [view, impactFilter, clinicalOnly],
  );

  if (!ticker) {
    return (
      <div className="grid h-[60vh] place-items-center text-center text-on-surface-variant">
        <div className="flex flex-col items-center gap-3">
          <Icon name="article" className="text-4xl text-outline" size="base" />
          <p className="font-body-main text-lg text-on-surface">Select a company to see its news.</p>
          <p className="font-data-sm text-data-sm">Load a ticker in the sidebar, then fetch its news stream.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="grid min-w-0 items-stretch gap-5 lg:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(210px,0.65fr)]">
      {/* Column 1 — Intelligence Stream */}
      <section className="relative min-h-0 min-w-0">
        <TerminalPanel
          className="h-[760px] lg:absolute lg:inset-0 lg:h-full"
          bodyClassName="flex-1 min-h-0 overflow-y-auto overscroll-contain p-1 space-y-1"
          title={
            <span className="flex items-center gap-2">
              <Icon name="rss_feed" size="xs" className="text-primary" />
              Intelligence Stream · {ticker}
            </span>
          }
          action={
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 font-data-sm text-data-sm text-on-surface-variant">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                </span>
                Live
              </span>
              <button
                onClick={ingest}
                disabled={!canIngest || ingesting}
                title={canIngest ? `Fetch news (${meta?.news_provider})` : "Set NEWS_PROVIDER to enable"}
                className="text-on-surface-variant hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Icon name={ingesting ? "progress_activity" : "download"} size="sm" className={ingesting ? "animate-spin" : ""} />
              </button>
            </div>
          }
        >
          {error && <ErrorNote message={error} />}
          {loading && !view ? (
            <Spinner label="Loading news…" />
          ) : articles.length === 0 ? (
            <p className="grid h-full place-items-center px-4 text-center font-data-sm text-data-sm text-on-surface-variant">
              {view && view.summary.total > 0
                ? "No articles match the impact filter."
                : canIngest
                  ? "No news yet — use ↓ to fetch the stream."
                  : "Enable a news provider to fetch the stream."}
            </p>
          ) : (
            articles.map((a) => <NewsCard key={a.id} a={a} />)
          )}
        </TerminalPanel>
      </section>

      {/* Column 2 — Impact Analysis */}
      <section className="flex min-w-0 flex-col gap-5">
        <div className="min-w-0 flex-1">
          <ReactionChart view={view} loading={loading} />
        </div>
        <div className="min-w-0">
          <CatalystMatrix rows={view?.catalyst_matrix ?? []} />
        </div>
      </section>

      {/* Column 3 — Intelligence & Filters */}
      <section className="flex min-w-0 flex-col gap-5 lg:col-span-2 xl:col-span-1">
        <TerminalPanel title="Intelligence & Filters" className="shrink-0" bodyClassName="divide-y divide-outline-variant px-5 pb-3">
        <TrendingTopicsPanel topics={view?.trending_topics ?? []} />
        <SectorSentimentPanel sectors={view?.sector_sentiment ?? []} />
        <FiltersPanel
          impactFilter={impactFilter}
          onToggle={toggleImpact}
          clinicalOnly={clinicalOnly}
          onClinicalToggle={() => setClinicalOnly((v) => !v)}
          summary={view?.summary}
        />
        <p className="py-3 text-xs text-on-surface-variant">Filters apply to the intelligence stream. Chart and sentiment summaries reflect the full dataset.</p>
        </TerminalPanel>
        <SignalPanel key={ticker} ticker={ticker} className="min-h-[300px] flex-1" reuseSaved />
      </section>
    </div>
  );
}

function NewsCard({ a }: { a: NewsArticle }) {
  const s = SENTIMENT[a.sentiment.label] ?? SENTIMENT.neutral;
  return (
    <article className="group relative border border-outline-variant bg-surface p-3 pl-4 transition-colors hover:bg-surface-container">
      <div className={`absolute bottom-0 left-0 top-0 w-1 ${s.bar} opacity-40`} />
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-data-sm text-data-sm text-on-surface-variant">{fmtTime(a.published_at)}</span>
          {a.source && (
            <span className="rounded-sm border border-outline-variant bg-surface-container-high px-1.5 py-0.5 font-data-sm text-data-sm text-secondary">
              {a.source}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {a.is_clinical && (
            <span
              className="flex items-center gap-0.5 rounded-sm border border-primary/40 bg-primary/10 px-1.5 py-0.5 font-label-caps text-[9px] uppercase text-primary"
              title={`Clinical relevance ${(a.clinical_relevance * 100).toFixed(0)}% (heuristic)`}
            >
              <Icon name="science" className="text-[10px]" size="xs" />
              Clinical
            </span>
          )}
          <span className={`rounded-sm border px-1.5 py-0.5 font-label-caps text-[9px] uppercase ${IMPACT_STYLE[a.impact] ?? IMPACT_STYLE.medium}`}>
            {a.impact}
          </span>
        </div>
      </div>
      <h3 className="mb-1 font-headline-panel text-headline-panel text-on-surface transition-colors group-hover:text-primary">
        {a.url ? (
          <a href={a.url} target="_blank" rel="noopener noreferrer">
            {a.headline}
          </a>
        ) : (
          a.headline
        )}
      </h3>
      {a.summary && <p className="mb-2 line-clamp-2 text-[12px] leading-relaxed text-on-surface-variant">{a.summary}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`flex items-center gap-1 rounded-sm border border-outline-variant bg-surface-container px-2 py-0.5 font-data-sm text-data-sm ${s.text}`}
          title={`${a.sentiment.method === "heuristic" ? "Heuristic (not verified)" : "Provider"} · score ${a.sentiment.score}`}
        >
          <Icon name={s.icon} className="text-[12px]" size="xs" />
          {s.word}
          {a.sentiment.method === "heuristic" && <span className="opacity-60">· heuristic</span>}
        </span>
        {a.tags.slice(0, 3).map((t) => (
          <span key={t} className="font-data-sm text-data-sm text-on-surface-variant">
            #{t}
          </span>
        ))}
      </div>
    </article>
  );
}

function ReactionChart({ view, loading }: { view: NewsView | null; loading: boolean }) {
  const series = view?.price_series ?? [];
  const markers = view?.markers ?? [];
  const last = series.length ? series[series.length - 1].close : null;
  const first = series.length ? series[0].close : null;
  const chg = last !== null && first ? last / first - 1 : null;

  return (
    <TerminalPanel
      className="h-full"
      bodyClassName="flex-1 min-h-0 p-3"
      title={
        <span className="flex items-center gap-2">
          <Icon name="candlestick_chart" size="xs" className="text-primary" />
          Market Reaction {view ? `· ${view.company.ticker}` : ""}
        </span>
      }
      action={
        last !== null ? (
          <span className="flex items-center gap-3 font-data-sm text-data-sm">
            <span className="text-on-surface-variant">
              Last <span className="text-on-surface">${last.toFixed(2)}</span>
            </span>
            {chg !== null && (
              <span className={chg >= 0 ? "text-primary" : "text-error"}>
                {chg >= 0 ? "+" : ""}
                {formatPct(chg)}
              </span>
            )}
          </span>
        ) : undefined
      }
    >
      {loading && !view ? (
        <Spinner label="Loading…" />
      ) : series.length < 2 ? (
        <p className="grid h-full place-items-center text-center font-data-sm text-data-sm text-on-surface-variant">
          No price history — sync prices for this company to plot the reaction chart.
        </p>
      ) : (
        <ChartSvg key={view?.company.ticker} series={series} markers={markers} />
      )}
    </TerminalPanel>
  );
}

function ChartSvg({
  series,
  markers,
}: {
  series: Array<{ date: string; close: number }>;
  markers: NewsMarker[];
}) {
  const [active, setActive] = useState<number | null>(null);
  const n = series.length;
  const min = Math.min(...series.map(p => p.close));
  const max = Math.max(...series.map(p => p.close));
  const padding = (max - min) * .12 || Math.max(Math.abs(max) * .02, 1);
  const low = min - padding, high = max + padding;
  const x = (i: number) => 60 + i / (n - 1) * 420;
  const y = (v: number) => 440 - (v - low) / (high - low) * 400;
  const line = series.map((p, i) => `${x(i)},${y(p.close)}`).join(" ");
  // Group coincident events so no news item hides another dot on the same day.
  const groups = new Map<number, NewsMarker[]>();
  for (const marker of markers) {
    if (marker.date < series[0].date || marker.date > series[n - 1].date) continue;
    let i = 0;
    for (let j = 1; j < n && series[j].date <= marker.date; j++) i = j;
    groups.set(i, [...(groups.get(i) ?? []), marker]);
  }
  const selected = active === null ? [] : groups.get(active) ?? [];
  const shortDate = (date: string) => new Date(`${date}T00:00:00`).toLocaleDateString(undefined, {month: "short", day: "numeric"});
  return <div className="w-full min-w-0">
    <p className="mb-2 text-xs text-on-surface-variant">Daily close · Hover, focus, or tap a news dot to inspect events.</p>
    <svg viewBox="0 0 510 490" className="mx-auto aspect-square w-full max-w-[520px]" aria-label="Daily closing prices with news and catalyst markers">
      {[0, 1, 2, 3, 4].map(t => {
        const value = low + (high - low) * t / 4;
        return <g key={t}><line x1="60" x2="480" y1={y(value)} y2={y(value)} stroke="currentColor" className="text-outline-variant" strokeDasharray="3 5" /><text x="52" y={y(value)+4} textAnchor="end" fill="currentColor" className="text-on-surface-variant" fontSize="11">${value.toFixed(high - low < 10 ? 2 : 0)}</text></g>;
      })}
      <polyline points={line} fill="none" stroke="currentColor" className="text-primary" strokeWidth="2.5" strokeLinejoin="round" />
      {[0, Math.floor((n - 1) / 2), n - 1].map(i => <text key={i} x={x(i)} y="470" textAnchor={i === 0 ? "start" : i === n-1 ? "end" : "middle"} fill="currentColor" className="text-on-surface-variant" fontSize="11">{shortDate(series[i].date)}</text>)}
      {[...groups].map(([i, events]) => <g key={i} role="button" tabIndex={0}
        aria-label={`${shortDate(series[i].date)}: ${events.length} events. ${events.map(m => m.label).join(". ")}`}
        onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)} onClick={() => setActive(i)}
        onKeyDown={event => { if (event.key === "Enter" || event.key === " ") {event.preventDefault(); setActive(i);} if(event.key === "Escape") setActive(null); }}
        className="cursor-pointer outline-none group">
        {active === i && <line x1={x(i)} x2={x(i)} y1="40" y2="440" stroke="currentColor" className="text-outline" strokeDasharray="4 4" />}
        <circle cx={x(i)} cy={y(series[i].close)} r="14" fill="transparent" />
        <circle cx={x(i)} cy={y(series[i].close)} r={active === i ? 8 : 6} fill="currentColor" className={`${events.some(m => m.kind !== "catalyst") ? "text-secondary" : "text-caution"} group-focus:stroke-current`} stroke="white" strokeWidth="2" />
        <title>{events.map(m => m.label).join("\n")}</title>
      </g>)}
    </svg>
    <div className="mb-3 flex flex-wrap gap-4 text-xs text-on-surface-variant"><span><span className="text-secondary">●</span> News</span><span><span className="text-caution">●</span> Catalyst</span><span>Line: daily close</span></div>
    <div className="h-36 overflow-y-auto overscroll-contain rounded-xl border border-outline-variant bg-surface-container-low p-3 text-xs" aria-live="polite">
      {active !== null && selected.length ? <><p className="mb-2 font-semibold">{shortDate(series[active].date)} · Close ${series[active].close.toFixed(2)} · {selected.length} event{selected.length === 1 ? "" : "s"}</p><ul className="space-y-3">{selected.map((m, i) => <li key={i}><p className="font-medium">{m.label}</p><p className="mt-1 text-on-surface-variant">{m.date} · {m.kind === "catalyst" ? "Clinical catalyst" : "News"}{m.sentiment ? ` · ${m.sentiment} sentiment` : ""}</p></li>)}</ul></> : <p className="text-on-surface-variant">{groups.size ? "Select a dot to see its headlines and event dates here. Events on non-trading days align to the preceding close." : "No news or catalyst events fall within this price window."}</p>}
    </div>
    <p className="mt-2 text-[11px] text-on-surface-variant">Events shown alongside prices do not establish that they caused a price move.</p>
  </div>;
}

function CatalystMatrix({ rows }: { rows: CatalystMatrixRow[] }) {
  return (
    <TerminalPanel
      className="max-h-[260px]"
      bodyClassName="flex-1 min-h-0 overflow-auto overscroll-contain p-0"
      title={
        <span className="flex items-center gap-2">
          <Icon name="hub" size="xs" className="text-on-surface-variant" />
          Catalyst Correlation Matrix
        </span>
      }
    >
      {rows.length === 0 ? (
        <p className="p-4 text-center font-data-sm text-data-sm text-on-surface-variant">
          No catalysts to correlate — ingest trials for this company first.
        </p>
      ) : (
        <table className="w-full text-left">
          <thead className="sticky top-0 border-b border-outline-variant bg-surface font-label-caps text-label-caps uppercase text-on-surface-variant">
            <tr>
              <th className="px-3 py-1.5 font-medium">Pipeline Asset</th>
              <th className="px-3 py-1.5 font-medium">Indication</th>
              <th className="px-3 py-1.5 font-medium">News Vol</th>
              <th className="px-3 py-1.5 font-medium">Sentiment</th>
              <th className="px-3 py-1.5 text-right font-medium">Conf.</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-outline-variant font-data-tabular text-data-tabular">
            {rows.map((r) => {
              const pos = r.sentiment_score >= 0;
              return (
                <tr key={r.asset} className="h-14 hover:bg-surface-container">
                  <td
                    className="max-w-[160px] truncate px-3 py-2 text-on-surface"
                    title={r.match_terms.length ? `Matched on: ${r.match_terms.join(", ")}` : r.asset}
                  >
                    {r.asset}
                  </td>
                  <td className="max-w-[140px] truncate px-3 py-2 text-on-surface-variant">{r.indication ?? "—"}</td>
                  <td className="px-3 py-2 text-on-surface">{r.news_volume}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-container-high">
                        <div className={`h-full ${pos ? "bg-primary" : "bg-error"}`} style={{ width: `${Math.min(100, Math.abs(r.sentiment_score) * 100)}%` }} />
                      </div>
                      <span className={pos ? "text-primary" : "text-error"}>{r.sentiment_score.toFixed(2)}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className="rounded-sm border border-outline-variant bg-surface-variant px-1.5 py-0.5 text-[10px] uppercase text-on-surface-variant">
                      {r.confidence}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </TerminalPanel>
  );
}

function InsightsSection({ title, children, bodyClassName }: { title: ReactNode; children: ReactNode; bodyClassName: string }) {
  return <section className="py-4"><h3 className="mb-3 text-sm font-semibold">{title}</h3><div className={bodyClassName}>{children}</div></section>;
}

function TrendingTopicsPanel({ topics }: { topics: TrendingTopic[] }) {
  return (
    <InsightsSection
      bodyClassName="flex flex-wrap gap-2 content-start overflow-y-auto"
      title={
        <span className="flex items-center gap-2">
          <Icon name="local_fire_department" size="xs" className="text-tertiary-fixed-dim" />
          Trending Topics
        </span>
      }
    >
      {topics.length === 0 ? (
        <span className="font-data-sm text-data-sm text-on-surface-variant">No topics yet.</span>
      ) : (
        topics.map((t, i) => (
          <span
            key={t.topic}
            className={`cursor-default rounded-sm border px-2 py-1 font-data-sm text-data-sm ${
              i === 0
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-outline-variant bg-surface-container-high text-on-surface"
            }`}
          >
            {t.topic} ({t.count})
          </span>
        ))
      )}
    </InsightsSection>
  );
}

function SectorSentimentPanel({ sectors }: { sectors: SectorSentiment[] }) {
  return (
    <InsightsSection
      bodyClassName="flex flex-col gap-2 overflow-y-auto"
      title={
        <span className="flex items-center gap-2">
          <Icon name="grid_view" size="xs" className="text-secondary" />
          Sector Sentiment
        </span>
      }
    >
      {sectors.length === 0 ? (
        <span className="font-data-sm text-data-sm text-on-surface-variant">No news across sectors yet.</span>
      ) : (
        sectors.map((s) => {
          const pos = s.avg_score >= 0;
          return (
            <div key={s.sector} className="flex items-center justify-between gap-2 font-data-sm text-data-sm">
              <span className="text-on-surface">{s.sector}</span>
              <div
                className={`flex h-4 w-20 shrink-0 items-center justify-center rounded-sm border ${
                  pos ? "border-primary/40 bg-primary/20" : "border-error/40 bg-error/20"
                }`}
              >
                <span className={pos ? "text-primary" : "text-error"}>
                  {pos ? "+" : ""}
                  {(s.avg_score * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          );
        })
      )}
    </InsightsSection>
  );
}

function FiltersPanel({
  impactFilter,
  onToggle,
  clinicalOnly,
  onClinicalToggle,
  summary,
}: {
  impactFilter: Set<string>;
  onToggle: (i: string) => void;
  clinicalOnly: boolean;
  onClinicalToggle: () => void;
  summary?: NewsView["summary"];
}) {
  return (
    <InsightsSection
      bodyClassName="space-y-3 overflow-y-auto"
      title={
        <span className="flex items-center gap-2">
          <Icon name="tune" size="xs" className="text-on-surface-variant" />
          Filters
        </span>
      }
    >
      <label className="flex cursor-pointer items-center justify-between rounded-sm border border-outline-variant bg-surface px-2 py-1.5">
        <span className="flex items-center gap-1.5 font-data-sm text-data-sm text-on-surface">
          <Icon name="science" size="xs" className="text-primary" />
          Clinical only
          {summary && <span className="text-on-surface-variant">({summary.clinical})</span>}
        </span>
        <input
          type="checkbox"
          checked={clinicalOnly}
          onChange={onClinicalToggle}
          className="h-3 w-3 rounded-sm border-outline-variant bg-surface text-primary focus:ring-0"
        />
      </label>

      <div>
        <div className="mb-2 font-label-caps text-label-caps uppercase text-on-surface-variant">Impact</div>
        <div className="space-y-1.5">
          {IMPACTS.map((i) => (
            <label key={i} className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={impactFilter.has(i)}
                onChange={() => onToggle(i)}
                className="h-3 w-3 rounded-sm border-outline-variant bg-surface text-primary focus:ring-0"
              />
              <span className="font-data-sm text-data-sm capitalize text-on-surface">{i}</span>
            </label>
          ))}
        </div>
      </div>
      {summary && (
        <div className="border-t border-outline-variant pt-2 font-data-sm text-data-sm text-on-surface-variant">
          {summary.total} articles ·{" "}
          <span className="text-primary">{summary.bullish} bull</span> /{" "}
          <span className="text-error">{summary.bearish} bear</span> / {summary.neutral} neut
        </div>
      )}
    </InsightsSection>
  );
}
