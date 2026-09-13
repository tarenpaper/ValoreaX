// Display formatting helpers for financial figures.

export function formatUSD(value: number | null | undefined, unit = "USD"): string {
  if (value === null || value === undefined) return "—";
  if (unit === "shares") return `${(value / 1e6).toLocaleString(undefined, { maximumFractionDigits: 1 })}M sh`;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(2)}`;
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

const CONCEPT_LABELS: Record<string, string> = {
  revenue: "Revenue",
  operating_income: "Operating income",
  ebitda: "EBITDA",
  cash: "Cash & equivalents",
  total_debt: "Total debt",
  shares_outstanding: "Shares outstanding",
  operating_cash_flow: "Operating cash flow",
  capex: "Capital expenditure",
  free_cash_flow: "Free cash flow",
  marketable_securities_current: "Marketable securities (current)",
  marketable_securities_noncurrent: "Marketable securities (non-current)",
  liquidity: "Liquidity",
  research_development: "R&D expense",
  sga: "SG&A expense",
};

/**
 * Formats a biotech figure by unit: USD, ratio (as %), or quarters of runway.
 * `signed` prefixes "+" for figures that are changes (e.g. dilution), not shares.
 */
export function formatFigure(value: number | null | undefined, unit: string, signed = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (unit === "ratio") return `${signed && value > 0 ? "+" : ""}${formatPct(value)}`;
  if (unit === "quarters") return `${value.toFixed(1)} qtrs`;
  return formatUSD(value, unit);
}

export function conceptLabel(concept: string): string {
  return CONCEPT_LABELS[concept] ?? concept.replace(/_/g, " ");
}

export function statusColor(status: string): string {
  switch (status) {
    case "reported":
      return "text-primary border-primary/30 bg-primary/10";
    case "derived":
      return "text-secondary border-secondary-container/50 bg-secondary-container/20";
    case "estimated":
      return "text-caution border-caution/40 bg-caution/10";
    case "inconsistent":
      return "text-error border-error/40 bg-error/10";
    case "missing":
    default:
      return "text-on-surface-variant border-outline-variant bg-surface-container";
  }
}

export function signalColor(signal: string): string {
  switch (signal) {
    case "long":
      return "text-primary";
    case "short":
      return "text-error";
    default:
      return "text-caution";
  }
}
