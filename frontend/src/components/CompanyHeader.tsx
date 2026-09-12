import type { CompanySummary, Metric } from "../types";
import { formatUSD, statusColor } from "../format";

const TILES: Array<{ concept: string; label: string }> = [
  { concept: "revenue", label: "Revenue" },
  { concept: "ebitda", label: "EBITDA" },
  { concept: "operating_income", label: "Operating income" },
  { concept: "cash", label: "Cash & equiv." },
  { concept: "total_debt", label: "Total debt" },
  { concept: "shares_outstanding", label: "Shares out." },
];

function sourceLabel(src: string | undefined): string {
  if (src === "sec_edgar") return "SEC";
  if (src === "derived") return "DERIVED";
  if (src === "mock") return "SAMPLE";
  return (src ?? "—").toUpperCase();
}

export default function CompanyHeader({ summary }: { summary: CompanySummary }) {
  const c = summary.company;
  const km = summary.key_metrics;
  const filingDate = km.revenue?.period_end ?? km.cash?.period_end ?? null;
  const isLive = c.source === "sec_edgar";

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-6 rounded-3xl bg-surface p-7 shadow-sm">
        <div className="flex items-center gap-5">
          <div className="hidden h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-surface-container font-editorial text-3xl sm:flex">{c.ticker.slice(0, 2)}</div>
          <div><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-semibold">{c.exchange ? `${c.exchange.toUpperCase()}: ` : ""}{c.ticker}</span><span className="rounded-full bg-surface-container px-3 py-1 text-[10px] font-semibold uppercase tracking-wide">{c.sector || "Healthcare"}</span><span className="rounded-full bg-primary/10 px-3 py-1 text-[10px] font-semibold text-primary">{isLive ? "SEC sourced" : "Sample company"}</span></div>
          <h2 className="mt-2 font-editorial text-3xl tracking-tight lg:text-4xl">{c.name}</h2><p className="mt-1 text-xs text-on-surface-variant">{c.industry || "Company research and intelligence"}{c.cik ? ` · CIK ${c.cik}` : ""}</p></div>
        </div>
        <div className="rounded-2xl bg-surface-container-low px-5 py-3"><p className="font-mono text-sm font-medium">{summary.latest_fiscal_year ? `FY ${summary.latest_fiscal_year}` : "Financial snapshot"}</p><p className="mt-1 text-xs text-on-surface-variant">{filingDate ? `Period ending ${filingDate}` : "No filings available"}</p></div>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {TILES.map(({ concept, label }) => {
          const m: Metric | undefined = km[concept];
          const missing = !m || m.value === null || m.quality.status === "missing";
          return (
            <div key={concept} className="flex min-h-[118px] flex-col justify-center rounded-2xl bg-surface px-5 py-4 shadow-sm">
              <div className="mb-1 font-label-caps text-label-caps uppercase text-on-surface-variant">
                {label}
              </div>
              <div className="font-data-tabular text-[19px] text-on-surface">
                {missing ? (
                  <span className="text-on-surface-variant opacity-50">—</span>
                ) : (
                  formatUSD(m!.value, m!.unit)
                )}
              </div>
              <div className="mt-1 flex">
                <span
                  className={`rounded-full px-2 py-1 font-data-sm text-[9px] ${
                    missing
                      ? "border-error/30 bg-error/10 text-error"
                      : statusColor(m!.quality.status)
                  }`}
                  title={m?.quality.note ?? undefined}
                >
                  {missing
                    ? "MISSING"
                    : `${sourceLabel(m!.source)} · ${(m!.quality.confidence * 100).toFixed(0)}%`}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {summary.data_quality_warnings.length > 0 && (
        <div className="border-t border-outline-variant px-4 py-2">
          <ul className="flex flex-wrap gap-x-4 font-data-sm text-data-sm text-caution">
            {summary.data_quality_warnings.map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
