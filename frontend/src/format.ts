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
};

export function conceptLabel(concept: string): string {
  return CONCEPT_LABELS[concept] ?? concept.replace(/_/g, " ");
}

export function statusColor(status: string): string {
  switch (status) {
    case "reported":
      return "text-long border-long/40 bg-long/10";
    case "derived":
      return "text-accent border-accent/40 bg-accent/10";
    case "estimated":
      return "text-watch border-watch/40 bg-watch/10";
    case "inconsistent":
      return "text-short border-short/40 bg-short/10";
    case "missing":
    default:
      return "text-muted border-edge bg-edge/40";
  }
}

export function signalColor(signal: string): string {
  switch (signal) {
    case "long":
      return "text-long";
    case "short":
      return "text-short";
    default:
      return "text-watch";
  }
}
