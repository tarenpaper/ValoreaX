import type { CompanySummary } from "../types";
import { formatUSD } from "../format";
import { Badge, Stat } from "./ui";

export default function CompanyHeader({ summary }: { summary: CompanySummary }) {
  const c = summary.company;
  const km = summary.key_metrics;
  const filingDate =
    km.revenue?.period_end ?? km.cash?.period_end ?? null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="font-mono text-2xl font-bold text-slate-100">{c.ticker}</h1>
        <span className="text-lg text-slate-300">{c.name}</span>
        {c.is_example && (
          <Badge className="border-watch/40 bg-watch/10 text-watch">example / sample data</Badge>
        )}
        <Badge className="border-edge text-muted" title="Data provider">
          {c.source}
        </Badge>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {c.sector && <span>{c.sector}</span>}
        {c.industry && <span>· {c.industry}</span>}
        {c.exchange && <span>· {c.exchange}</span>}
        {c.cik && <span>· CIK {c.cik}</span>}
        {summary.latest_fiscal_year && <span>· Latest FY{summary.latest_fiscal_year}</span>}
        {filingDate && <span>· Period end {filingDate}</span>}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Revenue" value={formatUSD(km.revenue?.value)} />
        <Stat label="Operating income" value={formatUSD(km.operating_income?.value)} />
        <Stat label="EBITDA" value={formatUSD(km.ebitda?.value)} />
        <Stat label="Cash" value={formatUSD(km.cash?.value)} />
        <Stat label="Total debt" value={formatUSD(km.total_debt?.value)} />
        <Stat
          label="Shares out."
          value={formatUSD(km.shares_outstanding?.value, "shares")}
        />
      </div>

      {summary.data_quality_warnings.length > 0 && (
        <div className="rounded-md border border-watch/30 bg-watch/5 px-3 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-watch">
            Data-quality warnings
          </p>
          <ul className="mt-1 list-disc pl-5 text-[11px] text-watch/90">
            {summary.data_quality_warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
