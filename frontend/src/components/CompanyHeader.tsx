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
    <section className="terminal-panel flex flex-col rounded-sm border border-outline-variant">
      {/* Identity row */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-outline-variant bg-surface-container-low p-4">
        <div>
          <div className="mb-1 flex items-end gap-3">
            <h2 className="font-display-ticker text-display-ticker tracking-tighter text-on-surface">
              {c.ticker}
            </h2>
            <span className="pb-1 font-body-main text-body-main text-on-surface-variant">{c.name}</span>
            <span className="ml-1 flex items-center gap-1 rounded-sm border border-outline-variant bg-surface px-1.5 py-0.5 pb-1 font-data-sm text-data-sm text-on-surface">
              <span
                className={`h-1.5 w-1.5 rounded-full ${isLive ? "animate-pulse bg-primary" : "bg-outline"}`}
              />
              {isLive ? "LIVE · SEC" : "SAMPLE"}
            </span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-data-sm text-data-sm text-on-surface-variant">
            {c.sector && <span>{c.sector}</span>}
            {c.industry && <span>· {c.industry}</span>}
            {c.exchange && <span>· {c.exchange}</span>}
            {c.cik && <span>· CIK {c.cik}</span>}
          </div>
        </div>
        <div className="text-right">
          <div className="font-data-tabular text-data-tabular text-on-surface">
            {summary.latest_fiscal_year ? `FY ${summary.latest_fiscal_year}` : "—"}
          </div>
          <div className="font-data-sm text-data-sm text-on-surface-variant">
            {filingDate ? `Period end ${filingDate}` : "no filings"}
          </div>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 gap-[1px] bg-outline-variant sm:grid-cols-3 lg:grid-cols-6">
        {TILES.map(({ concept, label }) => {
          const m: Metric | undefined = km[concept];
          const missing = !m || m.value === null || m.quality.status === "missing";
          return (
            <div key={concept} className="flex min-h-[64px] flex-col justify-center bg-surface px-3 py-2">
              <div className="mb-1 font-label-caps text-label-caps uppercase text-on-surface-variant">
                {label}
              </div>
              <div className="font-data-tabular text-[14px] text-on-surface">
                {missing ? (
                  <span className="text-on-surface-variant opacity-50">—</span>
                ) : (
                  formatUSD(m!.value, m!.unit)
                )}
              </div>
              <div className="mt-1 flex">
                <span
                  className={`rounded-sm border px-1 py-[1px] font-data-sm text-[9px] ${
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
