import type { Metric } from "../types";
import { conceptLabel, formatUSD, statusColor } from "../format";
import { Badge } from "./ui";

// The financial-input table: every value labelled with source, period, units,
// and extraction confidence/status — the transparency core of the product.
export default function FinancialTable({ metrics }: { metrics: Metric[] }) {
  const order = ["revenue", "operating_income", "ebitda", "cash", "total_debt", "shares_outstanding"];
  const rows = order.map((c) => metrics.find((m) => m.concept === c)).filter(Boolean) as Metric[];

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-muted">
            <th className="py-2 pr-3 font-medium">Metric</th>
            <th className="py-2 pr-3 text-right font-medium">Value</th>
            <th className="py-2 pr-3 font-medium">Period</th>
            <th className="py-2 pr-3 font-medium">Units</th>
            <th className="py-2 pr-3 font-medium">Source</th>
            <th className="py-2 pr-3 font-medium">Status</th>
            <th className="py-2 font-medium">Conf.</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-edge">
          {rows.map((m) => (
            <tr key={m.concept} className="align-top">
              <td className="py-2 pr-3 text-slate-200">{conceptLabel(m.concept)}</td>
              <td className="py-2 pr-3 text-right font-mono text-slate-100">
                {formatUSD(m.value, m.unit)}
              </td>
              <td className="py-2 pr-3 text-muted">
                {m.fiscal_year ? `FY${m.fiscal_year}` : "—"}
                {m.period_end && (
                  <span className="ml-1 text-[11px] text-slate-500">({m.period_end})</span>
                )}
              </td>
              <td className="py-2 pr-3 text-muted">{m.unit}</td>
              <td className="py-2 pr-3">
                <span className="text-muted">{m.source}</span>
                {m.provenance.xbrl_concept && (
                  <div
                    className="max-w-[220px] truncate text-[11px] text-slate-500"
                    title={`${m.provenance.xbrl_concept}${
                      m.provenance.accession_number
                        ? ` · ${m.provenance.form ?? ""} ${m.provenance.accession_number}`
                        : ""
                    }`}
                  >
                    {m.provenance.xbrl_concept}
                  </div>
                )}
              </td>
              <td className="py-2 pr-3">
                <Badge className={statusColor(m.quality.status)} title={m.quality.note ?? undefined}>
                  {m.quality.status}
                </Badge>
              </td>
              <td className="py-2 font-mono text-xs text-muted">
                {(m.quality.confidence * 100).toFixed(0)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-[11px] text-slate-500">
        Hover a source concept or status badge for the originating XBRL concept, filing accession,
        and any data-quality note. <span className="text-accent">reported</span> = taken directly
        from a filed fact; <span className="text-accent">derived</span> = computed from reported
        facts.
      </p>
    </div>
  );
}
