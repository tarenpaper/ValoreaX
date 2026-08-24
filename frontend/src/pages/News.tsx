import { useCallback, useEffect, useMemo, useState } from "react";
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
    <div className="flex h-[calc(100vh-8.5rem)] gap-2">
      {/* Column 1 — Intelligence Stream */}
      <section className="flex min-w-[340px] max-w-[460px] flex-1 flex-col">
        <TerminalPanel
          className="h-full"
          bodyClassName="flex-1 min-h-0 overflow-y-auto p-1 space-y-1"
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
      <section className="flex min-w-[440px] flex-[2] flex-col gap-2">
        <div className="flex-[3]">
          <ReactionChart view={view} loading={loading} />
        </div>
        <div className="flex-[2]">
          <CatalystMatrix rows={view?.catalyst_matrix ?? []} />
        </div>
      </section>

      {/* Column 3 — Intelligence & Filters */}
      <section className="flex w-64 shrink-0 flex-col gap-2">
        <TrendingTopicsPanel topics={view?.trending_topics ?? []} />
        <SectorSentimentPanel sectors={view?.sector_sentiment ?? []} />
        <FiltersPanel
          impactFilter={impactFilter}
          onToggle={toggleImpact}
          clinicalOnly={clinicalOnly}
          onClinicalToggle={() => setClinicalOnly((v) => !v)}
          summary={view?.summary}
        />
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
        <ChartSvg series={series} markers={markers} />
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
  const n = series.length;
  const closes = series.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  const x = (i: number) => (i / (n - 1)) * 100;
  const y = (v: number) => 96 - ((v - min) / span) * 92;
  const line = series.map((p, i) => `${x(i)},${y(p.close)}`).join(" ");

  const dateIndex = new Map(series.map((p, i) => [p.date, i]));
  const nearestIdx = (d: string) => {
    if (dateIndex.has(d)) return dateIndex.get(d)!;
    let best = 0;
    for (let i = 0; i < n; i++) if (series[i].date <= d) best = i;
    return best;
  };

  return (
    <div className="relative h-full w-full">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full">
        <defs>
          <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38E1C6" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#38E1C6" stopOpacity="0" />
          </linearGradient>
        </defs>
        <polyline points={`0,100 ${line} 100,100`} fill="url(#chartFill)" stroke="none" />
        <polyline points={line} fill="none" stroke="#38E1C6" strokeWidth="0.7" vectorEffect="non-scaling-stroke" />
        {markers.map((m, k) => {
          const i = nearestIdx(m.date);
          const color = m.kind === "catalyst" ? "#fbbb59" : m.sentiment === "bearish" ? "#ffb4ab" : "#60fee2";
          // Clinical-news dots scale with relevance; catalysts are fixed.
          const r = m.kind === "catalyst" ? 1.1 : 0.8 + (m.relevance ?? 0.5) * 1.0;
          return (
            <g key={k}>
              <line x1={x(i)} y1="0" x2={x(i)} y2="100" stroke={color} strokeWidth="0.4" strokeDasharray="1.5 1.5" opacity="0.5" vectorEffect="non-scaling-stroke" />
              <circle cx={x(i)} cy={y(series[i].close)} r={r} fill={color} vectorEffect="non-scaling-stroke">
                <title>{`${m.label}${m.relevance !== null ? ` (clinical ${(m.relevance * 100).toFixed(0)}%)` : ""}`}</title>
              </circle>
            </g>
          );
        })}
      </svg>
      {/* Marker legend */}
      <div className="absolute bottom-1 right-1 flex gap-3 font-data-sm text-[9px] text-on-surface-variant">
        <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-primary" /> Clinical news</span>
        <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-tertiary-fixed-dim" /> Catalyst</span>
      </div>
    </div>
  );
}

function CatalystMatrix({ rows }: { rows: CatalystMatrixRow[] }) {
  return (
    <TerminalPanel
      className="h-full"
      bodyClassName="flex-1 min-h-0 overflow-y-auto p-0"
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
                <tr key={r.asset} className="hover:bg-surface-container">
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

function TrendingTopicsPanel({ topics }: { topics: TrendingTopic[] }) {
  return (
    <TerminalPanel
      className="flex-1"
      bodyClassName="p-3 flex flex-wrap gap-2 content-start overflow-y-auto"
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
    </TerminalPanel>
  );
}

function SectorSentimentPanel({ sectors }: { sectors: SectorSentiment[] }) {
  return (
    <TerminalPanel
      className="flex-1"
      bodyClassName="p-3 flex flex-col gap-2 overflow-y-auto"
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
            <div key={s.sector} className="flex items-center justify-between font-data-sm text-data-sm">
              <span className="text-on-surface">{s.sector}</span>
              <div
                className={`flex h-4 w-32 items-center justify-center rounded-sm border ${
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
    </TerminalPanel>
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
    <TerminalPanel
      className="flex-1"
      bodyClassName="p-3 space-y-3 overflow-y-auto"
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
    </TerminalPanel>
  );
}
