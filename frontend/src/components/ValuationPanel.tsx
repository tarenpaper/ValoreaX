import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ValuationResponse } from "../types";
import { formatPct, formatPrice } from "../format";
import { ErrorNote, Icon, Spinner, TerminalPanel } from "./ui";

// Percent inputs are edited as whole numbers; the rest of the assumptions use defaults.
const EDITABLE = [
  { key: "revenue_growth", label: "Rev growth", pct: 15 },
  { key: "operating_margin", label: "Op margin", pct: 15 },
  { key: "wacc", label: "WACC", pct: 10 },
  { key: "terminal_growth", label: "Term growth", pct: 2.5 },
] as const;

const FIXED = { tax_rate: 0.21, capex_pct_revenue: 0.05, nwc_pct_revenue: 0.05, projection_years: 5 };

export default function ValuationPanel({ ticker, className = "" }: { ticker: string; className?: string }) {
  const [form, setForm] = useState<Record<string, number>>(
    Object.fromEntries(EDITABLE.map((f) => [f.key, f.pct])),
  );
  const [result, setResult] = useState<ValuationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  const run = useCallback(
    async (values: Record<string, number>) => {
      setBusy(true);
      setError(null);
      try {
        const assumptions: Record<string, number> = { ...FIXED };
        for (const f of EDITABLE) assumptions[f.key] = values[f.key] / 100;
        setResult(await api.valuation(ticker, assumptions));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [ticker],
  );

  useEffect(() => {
    setResult(null);
    run(form); // auto-run with defaults on load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  const base = result?.scenarios.base.implied_share_price ?? 0;

  return (
    <TerminalPanel
      title="VALUATION (DCF)"
      className={className}
      bodyClassName="p-4 flex-1 flex flex-col min-h-0 gap-3 overflow-y-auto"
      action={
        <button
          onClick={() => setEditing((e) => !e)}
          title="Edit assumptions"
          className="text-on-surface-variant hover:text-primary"
        >
          <Icon name="settings" size="sm" />
        </button>
      }
    >
      {/* Assumptions: read-only strip, or editable grid */}
      {editing ? (
        <div className="grid grid-cols-2 gap-2 rounded-sm border border-outline-variant bg-surface p-2">
          {EDITABLE.map((f) => (
            <label key={f.key} className="block">
              <span className="font-data-sm text-[9px] uppercase text-on-surface-variant">{f.label}</span>
              <div className="mt-0.5 flex items-center rounded-sm border border-outline-variant bg-background">
                <input
                  type="number"
                  step={0.5}
                  value={form[f.key]}
                  onChange={(e) => setForm({ ...form, [f.key]: Number(e.target.value) })}
                  className="w-full bg-transparent px-1.5 py-1 font-data-tabular text-data-tabular text-on-surface outline-none"
                />
                <span className="pr-1.5 font-data-sm text-data-sm text-on-surface-variant">%</span>
              </div>
            </label>
          ))}
          <button
            onClick={() => {
              run(form);
              setEditing(false);
            }}
            className="col-span-2 rounded-sm bg-primary-container px-2 py-1 font-data-tabular text-data-tabular font-semibold text-on-primary"
          >
            Run DCF
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between rounded-sm border border-outline-variant bg-surface px-2 py-1 font-data-sm text-[10px] text-on-surface-variant">
          <span>WACC: <span className="text-on-surface">{form.wacc}%</span></span>
          <span>Term: <span className="text-on-surface">{form.terminal_growth}%</span></span>
          <span>Growth: <span className="text-on-surface">{form.revenue_growth}%</span></span>
        </div>
      )}

      {error && <ErrorNote message={error} />}
      {busy && !result && <Spinner label="Valuing…" />}

      {result && (
        <>
          {/* Scenario cards */}
          <div className="grid grid-cols-3 gap-2">
            {(["bear", "base", "bull"] as const).map((s) => {
              const price = result.scenarios[s].implied_share_price;
              const delta = base ? price / base - 1 : 0;
              const highlight = s === "base";
              return (
                <div
                  key={s}
                  className={`flex flex-col items-center border p-2 ${
                    highlight ? "border-primary/50 bg-primary/5" : "border-outline-variant bg-surface"
                  }`}
                >
                  <span
                    className={`mb-1 font-label-caps text-[9px] uppercase ${
                      s === "bear" ? "text-error" : highlight ? "text-primary" : "text-on-surface-variant"
                    }`}
                  >
                    {s}
                  </span>
                  <span className={`font-data-tabular text-[12px] ${highlight ? "font-bold text-primary" : "text-on-surface"}`}>
                    {formatPrice(price)}
                  </span>
                  {!highlight && (
                    <span className={`font-data-sm text-[9px] ${delta >= 0 ? "text-primary" : "text-error"}`}>
                      {delta >= 0 ? "+" : ""}
                      {formatPct(delta)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {result.sensitivity && <Heatmap data={result.sensitivity} wacc={form.wacc / 100} g={form.terminal_growth / 100} />}
        </>
      )}
    </TerminalPanel>
  );
}

function Heatmap({
  data,
  wacc,
  g,
}: {
  data: NonNullable<ValuationResponse["sensitivity"]>;
  wacc: number;
  g: number;
}) {
  const flat = data.implied_share_price.flat().filter((v): v is number => v !== null);
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const nearest = (arr: number[], v: number) =>
    arr.reduce((best, x, i) => (Math.abs(x - v) < Math.abs(arr[best] - v) ? i : best), 0);
  const baseRow = nearest(data.wacc_values, wacc);
  const baseCol = nearest(data.terminal_growth_values, g);

  const shade = (v: number) => {
    if (max === min) return "rgba(56,225,198,0.15)";
    const t = (v - min) / (max - min);
    return t >= 0.5
      ? `rgba(56,225,198,${0.08 + 0.4 * (t - 0.5) * 2})`
      : `rgba(255,180,171,${0.08 + 0.4 * (0.5 - t) * 2})`;
  };

  return (
    <div className="flex flex-1 flex-col">
      <span className="mb-1 font-label-caps text-label-caps uppercase text-on-surface-variant">
        WACC × Terminal growth
      </span>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-data-tabular text-[9px]">
          <thead>
            <tr className="text-on-surface-variant">
              <th className="bg-surface-container p-1 font-normal"></th>
              {data.terminal_growth_values.map((tv, j) => (
                <th key={j} className={`bg-surface-container p-1 font-normal ${j === baseCol ? "text-primary" : ""}`}>
                  {formatPct(tv)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.implied_share_price.map((row, i) => (
              <tr key={i}>
                <td className={`bg-surface-container p-1 text-on-surface-variant ${i === baseRow ? "text-primary" : ""}`}>
                  {formatPct(data.wacc_values[i])}
                </td>
                {row.map((cell, j) => (
                  <td
                    key={j}
                    className={`p-1 text-center text-on-surface ${
                      i === baseRow && j === baseCol ? "font-bold text-primary ring-1 ring-inset ring-primary" : ""
                    }`}
                    style={{ backgroundColor: cell === null ? "transparent" : shade(cell) }}
                  >
                    {cell === null ? "—" : cell.toFixed(0)}
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
