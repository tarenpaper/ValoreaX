import type { ValuationResponse } from "../types";
import { formatPct, formatPrice, formatUSD } from "../format";

/** Keep the modeled estimate separate from the observed market price. */
export default function ValuationOverview({ result, busy }: { result: ValuationResponse; busy: boolean }) {
  const continuing = result.continuing_value?.value ?? 0;
  const parts = [
    { label: "Drug value", note: "Risk-adjusted cash flows", amount: result.asset_value },
    ...(continuing !== 0 ? [{ label: "Additional pipeline estimate", note: "Based on an industry analog", amount: continuing }] : []),
    { label: "Corporate overhead", note: "Present value of company costs", amount: -result.overhead_present_value },
    { label: result.net_cash < 0 ? "Net debt" : "Net cash", note: "Cash less debt", amount: result.net_cash },
  ];
  const scale = Math.max(1, ...parts.map(part => Math.abs(part.amount ?? 0)));
  return <div className="space-y-4">
    <div className="valuation-summary">
      <div className="valuation-estimate">
        <p className="valuation-eyebrow">MODELED VALUE / SHARE</p>
        <p className="mt-2 font-mono text-3xl font-semibold tracking-tight text-primary">{formatPrice(result.value_per_share)}</p>
        <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{result.equity_value == null ? "Insufficient drug inputs to calculate a company value." : result.value_per_share == null ? "Shares outstanding are needed to calculate a per-share value." : "Sum of the parts, after overhead and net cash."}</p>
      </div>
      <div className="valuation-market">
        <div><p className="valuation-eyebrow">LATEST CLOSE</p><p className="mt-2 font-mono text-xl font-medium">{formatPrice(result.current_price)}</p><p className="mt-1 text-[11px] text-on-surface-variant">{result.current_price == null ? "Price unavailable" : result.price_as_of ?? "Date unavailable"}{result.price_source === "mock" && " · Sample data"}</p></div>
        <div className="valuation-multiple"><p className="valuation-eyebrow">PRICE / SOTP</p><p className="mt-2 font-mono text-xl font-medium">{result.price_to_sotp == null ? "N/A" : `${result.price_to_sotp.toFixed(2)}×`}</p><p className="mt-1 text-[11px] leading-relaxed text-on-surface-variant">{result.price_to_sotp == null ? "Requires a price and positive modeled value." : "Current price relative to modeled value."}</p></div>
      </div>
    </div>
    {result.price_to_sotp != null && <p className="text-xs leading-relaxed text-on-surface-variant">{result.price_to_sotp < 1 ? "Price is below the modeled value" : result.price_to_sotp > 1 ? "Price is above the modeled value" : "Price matches the modeled value"}. A 1.00× multiple means price equals the sum-of-the-parts estimate.{busy && " Updating the estimate…"}</p>}
    <div className="valuation-bridge">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-semibold">How the total is built</h3><span className="text-[11px] text-on-surface-variant">Company value · USD</span></div>
      <dl className="space-y-3">{parts.map(part => <div key={part.label} className="valuation-bridge-row">
        <dt><span className="block text-xs font-medium">{part.label}</span><span className="mt-1 block text-[10px] text-on-surface-variant">{part.note}</span></dt>
        <dd className="valuation-bridge-bar" aria-hidden="true"><span className={part.amount != null && part.amount < 0 ? "bg-caution" : part.label === "Additional pipeline estimate" ? "bg-secondary" : "bg-primary"} style={{ width: `${Math.abs(part.amount ?? 0) / scale * 100}%` }} /></dd>
        <dd className="text-right font-mono text-xs">{part.amount == null ? "—" : `${part.amount > 0 ? "+" : part.amount < 0 ? "−" : ""}${formatUSD(Math.abs(part.amount))}`}</dd>
      </div>)}</dl>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-outline-variant pt-4"><span className="text-sm font-semibold">Total equity value</span><span className="font-mono text-lg font-semibold">{formatUSD(result.equity_value)}</span></div>
      {result.shares_outstanding != null && <p className="mt-2 text-xs text-on-surface-variant">Divided by {result.shares_outstanding.toLocaleString(undefined, { maximumFractionDigits: 0 })} shares outstanding{result.discount_rate ? ` · ${formatPct(result.discount_rate, 2)} discount rate` : ""}.</p>}
      {result.continuing_value?.note && continuing !== 0 && <p className="mt-3 rounded-lg bg-caution/10 p-3 text-xs leading-relaxed text-caution">{result.continuing_value.note}</p>}
    </div>
  </div>;
}
