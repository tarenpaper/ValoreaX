import type { Metric } from "../types";
import { conceptLabel, formatUSD } from "../format";
import { Icon, TerminalPanel } from "./ui";

const ORDER = [
  "revenue", "operating_income", "ebitda", "operating_cash_flow", "capex", "free_cash_flow",
  "research_development", "sga", "cash", "marketable_securities_current",
  "marketable_securities_noncurrent", "liquidity", "total_debt", "shares_outstanding",
];

function provChip(source: string, status: string) {
  if (status === "missing") {
    return { icon: "block", label: "MISSING", cls: "border-error/30 bg-error/10 text-error" };
  }
  if (source === "derived" || status === "derived") {
    return { icon: "calculate", label: "CALC", cls: "border-secondary-container/50 bg-secondary-container/20 text-secondary" };
  }
  if (source === "sec_edgar") {
    return { icon: "database", label: "SEC", cls: "border-outline-variant bg-surface-container text-on-surface-variant" };
  }
  return { icon: "database", label: source.toUpperCase(), cls: "border-outline-variant bg-surface-container text-on-surface-variant" };
}

// Financial inputs pivoted to concept × fiscal-year, every row carrying its
// source + extraction status — the transparency core of the product.
export default function FinancialTable({ metrics, className = "" }: { metrics: Metric[]; className?: string }) {
  const years = [...new Set(metrics.map((m) => m.fiscal_year).filter((y): y is number => y !== null))]
    .sort((a, b) => b - a)
    .slice(0, 4);

  const byConcept = (concept: string) => metrics.filter((m) => m.concept === concept);
  const cell = (concept: string, year: number) =>
    byConcept(concept).find((m) => m.fiscal_year === year) ?? null;
  const latest = (concept: string) => cell(concept, years[0]) ?? byConcept(concept)[0] ?? null;

  const rows = ORDER.map((c) => ({ concept: c, latest: latest(c) })).filter((r) => r.latest);

  return (
    <TerminalPanel
      title="FINANCIALS (SEC NORMALIZED)"
      className={className}
      bodyClassName="flex-1 min-h-0 overflow-auto p-0"
    >
      <table className="w-full whitespace-nowrap text-left font-data-tabular text-data-tabular">
        <thead className="sticky top-0 z-10 bg-surface-container font-label-caps text-[10px] text-on-surface-variant">
          <tr>
            <th className="w-1/3 border-b border-outline-variant px-4 py-2 font-normal">CONCEPT</th>
            {years.map((y) => (
              <th key={y} className="border-b border-outline-variant px-4 py-2 text-right font-normal">
                FY {y}
              </th>
            ))}
            <th className="w-24 border-b border-outline-variant px-4 py-2 text-center font-normal">PROV</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-outline-variant/30 text-on-surface">
          {rows.map(({ concept, latest: lm }) => {
            const chip = provChip(lm!.source, lm!.quality.status);
            return (
              <tr
                key={concept}
                className="h-8 hover:bg-surface-container-high"
                title={
                  lm!.provenance.xbrl_concept
                    ? `${lm!.provenance.xbrl_concept}${
                        lm!.provenance.accession_number
                          ? ` · ${lm!.provenance.form ?? ""} ${lm!.provenance.accession_number}`
                          : ""
                      }`
                    : undefined
                }
              >
                <td className="px-4 py-1 text-on-surface">{conceptLabel(concept)}</td>
                {years.map((y, i) => {
                  const m = cell(concept, y);
                  const isLatest = i === 0;
                  return (
                    <td
                      key={y}
                      className={`px-4 py-1 text-right ${
                        isLatest ? "font-bold text-primary" : "text-on-surface"
                      } ${m && m.value !== null && m.value < 0 ? "text-error" : ""}`}
                    >
                      <span title={m?.quality.note ?? undefined}>{m && m.value !== null && m.quality.status !== "missing" ? formatUSD(m.value, m.unit) : "—"}</span>
                    </td>
                  );
                })}
                <td className="px-4 py-1 text-center">
                  <span
                    className={`inline-flex items-center gap-1 rounded-sm border px-1 py-[2px] font-data-sm text-[9px] ${chip.cls}`}
                    title={lm!.quality.note ?? undefined}
                  >
                    <Icon name={chip.icon} className="text-[9px]" size="xs" />
                    {chip.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TerminalPanel>
  );
}
