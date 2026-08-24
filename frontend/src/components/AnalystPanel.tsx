import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { AnalystConsensus, AnalystRating } from "../types";
import { formatPct, formatPrice } from "../format";
import { ErrorNote, Icon, Spinner, TerminalPanel } from "./ui";

function toneClass(text: string | null | undefined): string {
  const t = (text ?? "").toLowerCase();
  if (/(strong buy|buy|outperform|overweight|accumulate|positive|add)/.test(t)) return "text-primary";
  if (/(strong sell|sell|underperform|underweight|reduce|negative)/.test(t)) return "text-error";
  return "text-on-surface-variant";
}

export default function AnalystPanel({
  ticker,
  analystProvider,
  className = "",
}: {
  ticker: string;
  analystProvider: string | null;
  className?: string;
}) {
  const [consensus, setConsensus] = useState<AnalystConsensus | null>(null);
  const [ratings, setRatings] = useState<AnalystRating[]>([]);
  const [loading, setLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canIngest = analystProvider === "fmp" || analystProvider === "mock";

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const res = await api.getAnalysts(t);
      setConsensus(res.consensus);
      setRatings(res.ratings);
    } catch {
      setConsensus(null);
      setRatings([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(ticker);
  }, [ticker, load]);

  async function ingest() {
    setIngesting(true);
    setError(null);
    try {
      const res = await api.ingestAnalysts(ticker);
      setConsensus(res.consensus);
      setRatings(res.ratings);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setIngesting(false);
    }
  }

  return (
    <TerminalPanel
      title="ANALYST CONSENSUS"
      className={className}
      bodyClassName="p-4 flex-1 flex flex-col min-h-0 gap-3"
      action={
        <div className="flex items-center gap-2">
          {consensus && (
            <span className="rounded-sm border border-outline-variant bg-surface px-1 py-0.5 font-data-sm text-[9px] text-on-surface-variant">
              N={consensus.analyst_count}
            </span>
          )}
          <button
            onClick={ingest}
            disabled={!canIngest || ingesting}
            title={
              canIngest
                ? `Fetch ratings (${analystProvider?.toUpperCase()})`
                : "Set ANALYST_PROVIDER=fmp (or mock) to enable"
            }
            className="text-on-surface-variant hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon name={ingesting ? "progress_activity" : "download"} size="sm" className={ingesting ? "animate-spin" : ""} />
          </button>
        </div>
      }
    >
      {error && <ErrorNote message={error} />}
      {loading ? (
        <Spinner label="Loading coverage…" />
      ) : !consensus ? (
        <p className="grid flex-1 place-items-center text-center font-data-sm text-data-sm text-on-surface-variant">
          {canIngest ? "No coverage yet — use ↓ to fetch analyst ratings." : "No analyst provider enabled."}
        </p>
      ) : (
        <>
          {/* Label + distribution */}
          <div className="flex items-center gap-4">
            <div
              className={`border border-outline-variant bg-surface px-3 py-1 font-display-ticker text-[20px] ${toneClass(consensus.consensus_label)}`}
            >
              {(consensus.consensus_label ?? "—").toUpperCase()}
            </div>
            <Distribution consensus={consensus} />
          </div>

          {/* Price-target range */}
          <TargetRange consensus={consensus} />

          {/* Institution list */}
          <div className="min-h-0 flex-1 overflow-y-auto rounded-sm border border-outline-variant bg-surface">
            <table className="w-full text-left font-data-tabular text-[10px]">
              <thead className="sticky top-0 bg-surface-container font-label-caps text-[9px] text-on-surface-variant">
                <tr>
                  <th className="border-b border-outline-variant px-2 py-1 font-normal">FIRM</th>
                  <th className="border-b border-outline-variant px-2 py-1 text-right font-normal">TARGET</th>
                  <th className="border-b border-outline-variant px-2 py-1 text-center font-normal">CHG</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/50 text-on-surface">
                {ratings.map((r, i) => (
                  <tr key={`${r.institution}-${i}`} className="hover:bg-surface-container-high">
                    <td className="max-w-[120px] truncate px-2 py-1.5">
                      {r.institution}
                      {r.grade && <span className={`ml-1 ${toneClass(r.grade)}`}>· {r.grade}</span>}
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      {r.price_target !== null ? formatPrice(r.price_target) : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      {r.action === "upgrade" ? (
                        <Icon name="arrow_upward" className="text-[10px] text-primary" size="xs" />
                      ) : r.action === "downgrade" ? (
                        <Icon name="arrow_downward" className="text-[10px] text-error" size="xs" />
                      ) : (
                        <span className="text-on-surface-variant">–</span>
                      )}
                    </td>
                  </tr>
                ))}
                {ratings.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-center text-on-surface-variant">
                      No per-institution grades on this plan.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </TerminalPanel>
  );
}

function Distribution({ consensus }: { consensus: AnalystConsensus }) {
  const d = consensus.distribution;
  const total = consensus.analyst_count || d.strong_buy + d.buy + d.hold + d.sell + d.strong_sell;
  if (total === 0) return null;
  const buy = d.strong_buy + d.buy;
  const sell = d.sell + d.strong_sell;
  return (
    <div className="flex-1">
      <div className="flex h-2 w-full gap-[1px] overflow-hidden rounded-sm">
        {buy > 0 && <div className="bg-primary/80" style={{ width: `${(buy / total) * 100}%` }} />}
        {d.hold > 0 && <div className="bg-outline-variant" style={{ width: `${(d.hold / total) * 100}%` }} />}
        {sell > 0 && <div className="bg-error/80" style={{ width: `${(sell / total) * 100}%` }} />}
      </div>
      <div className="mt-1 flex justify-between font-data-sm text-[9px] text-on-surface-variant">
        <span>{buy} BUY</span>
        <span>{d.hold} HOLD</span>
        <span>{sell} SELL</span>
      </div>
    </div>
  );
}

function TargetRange({ consensus }: { consensus: AnalystConsensus }) {
  const { low, high, consensus: mid } = consensus.targets;
  const price = consensus.current_price;
  if (low === null || high === null) return null;
  const lo = Math.min(low, price ?? low);
  const hi = Math.max(high, price ?? high);
  const span = hi - lo || 1;
  const pct = (v: number) => ((v - lo) / span) * 100;

  return (
    <div>
      <div className="mb-2 font-label-caps text-label-caps uppercase text-on-surface-variant">
        Price target range
      </div>
      <div className="relative flex h-6 items-center">
        <div className="absolute h-1 w-full rounded-full border border-outline-variant bg-surface-container-highest" />
        <div className="absolute h-1 bg-outline-variant" style={{ left: `${pct(low)}%`, right: `${100 - pct(high)}%` }} />
        {price !== null && (
          <div
            className="absolute z-10 h-4 w-1 bg-primary shadow-[0_0_4px_rgba(56,225,198,0.6)]"
            style={{ left: `${pct(price)}%` }}
            title={`Current: ${formatPrice(price)}`}
          />
        )}
        <span className="absolute -top-3 font-data-tabular text-[9px] text-on-surface-variant" style={{ left: `${pct(low)}%` }}>
          {formatPrice(low)}
        </span>
        {mid !== null && (
          <span className="absolute -top-3 -translate-x-1/2 font-data-tabular text-[9px] text-primary" style={{ left: `${pct(mid)}%` }}>
            {formatPrice(mid)}
          </span>
        )}
        <span className="absolute -top-3 -translate-x-full font-data-tabular text-[9px] text-on-surface-variant" style={{ left: `${pct(high)}%` }}>
          {formatPrice(high)}
        </span>
      </div>
      {consensus.implied_upside !== null && (
        <div className="mt-1 text-right font-data-sm text-data-sm text-on-surface">
          Implied Upside:{" "}
          <span className={consensus.implied_upside >= 0 ? "text-primary" : "text-error"}>
            {consensus.implied_upside >= 0 ? "+" : ""}
            {formatPct(consensus.implied_upside)}
          </span>
        </div>
      )}
    </div>
  );
}
