import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { ValuationResponse } from "../types";
import { formatPct, formatPrice, formatUSD } from "../format";
import { Badge, ErrorNote, Spinner, Stat } from "./ui";

interface FieldDef {
  key: string;
  label: string;
  kind: "pct" | "years";
  default: number; // stored as decimal for pct fields
}

const FIELDS: FieldDef[] = [
  { key: "revenue_growth", label: "Revenue growth", kind: "pct", default: 0.12 },
  { key: "operating_margin", label: "Operating margin", kind: "pct", default: 0.15 },
  { key: "tax_rate", label: "Tax rate", kind: "pct", default: 0.21 },
  { key: "capex_pct_revenue", label: "Capex % rev (net of D&A)", kind: "pct", default: 0.05 },
  { key: "nwc_pct_revenue", label: "ΔWorking capital % rev", kind: "pct", default: 0.05 },
  { key: "wacc", label: "WACC", kind: "pct", default: 0.1 },
  { key: "terminal_growth", label: "Terminal growth", kind: "pct", default: 0.025 },
  { key: "projection_years", label: "Projection years", kind: "years", default: 5 },
];

const SOURCE_BADGE: Record<string, string> = {
  sec: "border-long/40 bg-long/10 text-long",
  override: "border-accent/40 bg-accent/10 text-accent",
  default: "border-watch/40 bg-watch/10 text-watch",
};

export default function ValuationPanel({ ticker }: { ticker: string }) {
  const [form, setForm] = useState<Record<string, number>>(
    Object.fromEntries(FIELDS.map((f) => [f.key, f.kind === "pct" ? f.default * 100 : f.default])),
  );
  const [result, setResult] = useState<ValuationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const assumptions: Record<string, number> = {};
      for (const f of FIELDS) {
        assumptions[f.key] = f.kind === "pct" ? form[f.key] / 100 : form[f.key];
      }
      setResult(await api.valuation(ticker, assumptions));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const scenarioColor: Record<string, string> = {
    base: "text-slate-100",
    bull: "text-long",
    bear: "text-short",
  };

  return (
    <div className="space-y-4">
      {/* User assumptions */}
      <div>
        <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">Your assumptions</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {FIELDS.map((f) => (
            <label key={f.key} className="block">
              <span className="text-[11px] text-muted">{f.label}</span>
              <div className="mt-0.5 flex items-center rounded-md border border-edge bg-ink">
                <input
                  type="number"
                  step={f.kind === "years" ? 1 : 0.5}
                  value={form[f.key]}
                  onChange={(e) => setForm({ ...form, [f.key]: Number(e.target.value) })}
                  className="w-full bg-transparent px-2 py-1.5 font-mono text-sm outline-none"
                />
                <span className="pr-2 text-xs text-muted">{f.kind === "pct" ? "%" : "yr"}</span>
              </div>
            </label>
          ))}
        </div>
        <button
          onClick={run}
          disabled={busy}
          className="mt-3 rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-ink disabled:opacity-50"
        >
          {busy ? "Running…" : "Run DCF (base · bull · bear)"}
        </button>
      </div>

      {busy && <Spinner label="Valuing…" />}
      {error && <ErrorNote message={error} />}

      {result && (
        <>
          {/* SEC-derived inputs */}
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">
              Model inputs {result.inputs.fiscal_year ? `(FY${result.inputs.fiscal_year})` : ""}
            </p>
            <div className="grid grid-cols-3 gap-2">
              <Stat
                label="Base revenue"
                value={formatUSD(result.inputs.base_revenue)}
                sub={<SourceTag src={result.inputs.sources.base_revenue} />}
              />
              <Stat
                label="Net debt"
                value={formatUSD(result.inputs.net_debt)}
                sub={<SourceTag src={result.inputs.sources.net_debt} />}
              />
              <Stat
                label="Shares out."
                value={formatUSD(result.inputs.shares_outstanding, "shares")}
                sub={<SourceTag src={result.inputs.sources.shares_outstanding} />}
              />
            </div>
            {result.inputs.warnings.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-[11px] text-watch">
                {result.inputs.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>

          {/* Calculated outputs */}
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">
              Calculated outputs — implied share price
            </p>
            <div className="grid grid-cols-3 gap-2">
              {(["bear", "base", "bull"] as const).map((s) => {
                const sc = result.scenarios[s];
                return (
                  <div key={s} className="rounded-md border border-edge bg-ink/40 p-3">
                    <div className="text-[10px] uppercase tracking-wider text-muted">{s}</div>
                    <div className={`font-mono text-2xl ${scenarioColor[s]}`}>
                      {formatPrice(sc.implied_share_price)}
                    </div>
                    <dl className="mt-2 space-y-0.5 text-[11px] text-muted">
                      <Row k="EV" v={formatUSD(sc.enterprise_value)} />
                      <Row k="Equity" v={formatUSD(sc.equity_value)} />
                      <Row k="PV(TV)" v={formatPct(sc.pv_terminal_value / sc.enterprise_value)} />
                    </dl>
                    {sc.warnings.length > 0 && (
                      <p className="mt-1 text-[10px] text-watch">{sc.warnings[0]}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {result.sensitivity && <Sensitivity data={result.sensitivity} />}

          <p className="text-[11px] italic text-slate-500">{result.disclaimer}</p>
        </>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between">
      <dt>{k}</dt>
      <dd className="font-mono text-slate-300">{v}</dd>
    </div>
  );
}

function SourceTag({ src }: { src: string }) {
  return <Badge className={SOURCE_BADGE[src] ?? SOURCE_BADGE.default}>{src}</Badge>;
}

function Sensitivity({ data }: { data: NonNullable<ValuationResponse["sensitivity"]> }) {
  // Colour cells relative to the min/max implied price for a quick read.
  const flat = data.implied_share_price.flat().filter((v): v is number => v !== null);
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const shade = (v: number) => {
    if (max === min) return 0.15;
    return 0.08 + 0.32 * ((v - min) / (max - min));
  };

  return (
    <div>
      <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">
        Sensitivity — implied price (rows: WACC, cols: terminal growth)
      </p>
      <div className="overflow-x-auto">
        <table className="border-collapse text-xs">
          <thead>
            <tr>
              <th className="p-1 text-muted">WACC \ g</th>
              {data.terminal_growth_values.map((g) => (
                <th key={g} className="p-1 text-center font-mono text-muted">
                  {formatPct(g)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.implied_share_price.map((row, i) => (
              <tr key={i}>
                <td className="p-1 font-mono text-muted">{formatPct(data.wacc_values[i])}</td>
                {row.map((cell, j) => (
                  <td
                    key={j}
                    className="p-1 text-center font-mono text-slate-100"
                    style={{
                      backgroundColor:
                        cell === null ? "transparent" : `rgba(56, 189, 248, ${shade(cell)})`,
                    }}
                  >
                    {cell === null ? "—" : `$${cell.toFixed(2)}`}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
