// Display formatting helpers for financial figures.

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// Financial totals use whole dollars; per-share prices retain cents.
export function formatUSD(value: number | null | undefined, unit = "USD"): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (unit === "shares") return `${formatNumber(value)} sh`;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  return `${sign}$${formatNumber(abs)}`;
}

/** Compact card labels; tables and inputs continue to use full grouped amounts. */
export function formatCompactUSD(value: number | null | undefined, unit = "USD"): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  const scales = [{ divisor: 1e6, suffix: "M" }, { divisor: 1e9, suffix: "B" }, { divisor: 1e12, suffix: "T" }];
  let index = abs >= 1e12 ? 2 : abs >= 1e9 ? 1 : abs >= 1e6 ? 0 : -1;
  if (index < 0) return formatUSD(value, unit);
  // Promote a rounded 1,000M to 1B (and 1,000B to 1T).
  if (index < scales.length - 1 && Math.round(abs / scales[index].divisor * 100) / 100 >= 1000) index++;
  const scale = scales[index];
  const amount = (abs / scale.divisor).toLocaleString("en-US", { maximumFractionDigits: 2 });
  return `${value < 0 ? "-" : ""}${unit === "shares" ? "" : "$"}${amount}${scale.suffix}${unit === "shares" ? " sh" : ""}`;
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value < 0 ? "-" : ""}$${formatNumber(Math.abs(value), 2)}`;
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${formatNumber(value * 100, digits)}%`;
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
  if (unit === "quarters") return `${formatNumber(value, 1)} qtrs`;
  return formatCompactUSD(value, unit);
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
