import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  DrugAsset,
  Provenance,
  ValuationResponse,
  ValuedAsset,
} from "../types";
import { formatPct, formatPrice, formatUSD } from "../format";
import { Badge, ErrorNote, Icon, Spinner, TerminalPanel } from "./ui";

/**
 * Sum-of-the-parts valuation: every drug is its own mini-company model (rNPV), and the
 * drugs aggregate into one company value. There is no terminal value — a drug's revenue
 * ends when its exclusivity does.
 *
 * The panel builds itself: it syncs the drug models from the latest 10-K on load, so the
 * user never enters data. Everything the filing supplied stays editable, and an edit is
 * kept apart from the extracted value so a newer filing never erases it.
 */

const DEFAULT_DISCOUNT_RATE = 0.1;

const KIND_STYLE: Record<string, string> = {
  marketed: "text-primary border-primary/30 bg-primary/10",
  pipeline:
    "text-secondary border-secondary-container/50 bg-secondary-container/20",
  royalty: "text-caution border-caution/40 bg-caution/10",
};

/** How each modelled number was arrived at. Nothing derived may read as reported. */
const PROVENANCE_LABEL: Record<Provenance, string> = {
  sec: "Reported in XBRL",
  sec_quoted: "Quoted from the filing text",
  derived: "Derived from the company's own figures",
  benchmark: "Published industry benchmark",
  override: "Your edit",
};
const PROVENANCE_STYLE: Record<Provenance, string> = {
  sec: "text-primary border-primary/30 bg-primary/10",
  sec_quoted: "text-primary border-primary/30 bg-primary/10",
  derived:
    "text-secondary border-secondary-container/50 bg-secondary-container/20",
  benchmark: "text-caution border-caution/40 bg-caution/10",
  override: "text-on-surface border-outline bg-surface-container",
};

/** Editable inputs, shown in the drawer. Ratios are edited as whole percentages. */
const OVERRIDE_FIELDS = [
  { key: "base_revenue", label: "Current sales", kind: "usd" },
  { key: "peak_sales", label: "Peak sales", kind: "usd" },
  { key: "probability", label: "Probability", kind: "pct" },
  { key: "loe_year", label: "Exclusivity ends", kind: "year" },
  { key: "launch_year", label: "Launch year", kind: "year" },
  { key: "years_to_peak", label: "Years to peak", kind: "int" },
] as const;

const phaseLabel = (phase: string | null) =>
  phase ? phase.replace(/_/g, " ") : "—";

export default function ValuationPanel({
  ticker,
  className = "",
  onChange,
}: {
  ticker: string;
  className?: string;
  /** Fires when the models change, so research can re-read the same valuation. */
  onChange?: (discountRate: number) => void;
}) {
  const [result, setResult] = useState<ValuationResponse | null>(null);
  const [drugs, setDrugs] = useState<DrugAsset[]>([]);
  const [discountRate, setDiscountRate] = useState(DEFAULT_DISCOUNT_RATE);
  const [status, setStatus] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const value = useCallback(
    async (rate: number) => {
      const [valuation, listing] = await Promise.all([
        api.valuation(ticker, { discount_rate: rate }),
        api.drugs(ticker),
      ]);
      setResult(valuation);
      setDrugs(listing.drugs);
    },
    [ticker],
  );

  // Build the models from the filing, then value them. The sync is cheap after the first
  // run: the backend skips it until the company files a new 10-K.
  useEffect(() => {
    let active = true;
    setResult(null);
    setDrugs([]);
    setError(null);
    setOpen(null);
    setStatus("Reading the latest 10-K…");
    (async () => {
      try {
        const sync = await api.syncDrugs(ticker);
        if (!active) return;
        setWarnings(sync.warnings);
        setStatus("Valuing each drug…");
        await value(discountRate);
        if (active) onChange?.(discountRate);
      } catch (e) {
        if (active) setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        if (active) setStatus(null);
      }
    })();
    return () => {
      active = false;
    };
    // The discount rate re-values through `revalue`, not by rebuilding the models.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  const revalue = async (rate: number) => {
    setDiscountRate(rate);
    setBusy(true);
    try {
      await value(rate);
      onChange?.(rate);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const edit = async (
    id: number,
    payload: Parameters<typeof api.updateDrug>[1],
  ) => {
    setBusy(true);
    try {
      await api.updateDrug(id, payload);
      await value(discountRate);
      onChange?.(discountRate);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const total = result?.asset_value ?? 0;

  return (
    <TerminalPanel
      title="Sum-of-the-Parts Drug Valuation"
      className={className}
      bodyClassName="px-6 pb-6 flex-1 flex flex-col min-h-0 gap-3 overflow-y-auto"
      action={
        <label className="flex items-center gap-1.5 font-data-sm text-[10px] text-on-surface-variant">
          Discount rate
          <input
            type="number"
            step={0.5}
            min={1}
            max={50}
            value={+(discountRate * 100).toFixed(1)}
            onChange={(e) => revalue(Number(e.target.value) / 100)}
            className="w-14 rounded-sm border border-outline-variant bg-background px-1.5 py-1 text-right font-data-tabular text-data-tabular text-on-surface outline-none"
          />
          %
        </label>
      }
    >
      {error && <ErrorNote message={error} />}
      {status && !result && <Spinner label={status} />}

      {result && (
        <>
          <Headline result={result} />
          {result.note && (
            <p className="rounded-sm border border-outline-variant bg-surface px-3 py-2 font-data-sm text-[10px] text-on-surface-variant">
              {result.note}
            </p>
          )}
          {warnings.map((warning) => (
            <p key={warning} className="font-data-sm text-[10px] text-caution">
              {warning}
            </p>
          ))}

          {result.assets.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[34rem] table-fixed border-collapse font-data-sm text-[10px]">
                <thead className="text-on-surface-variant">
                  <tr className="border-b border-outline-variant text-left">
                    <th className="w-[26%] py-1.5 font-normal">Drug</th>
                    <th className="w-[15%] py-1.5 font-normal">Stage</th>
                    <th className="w-[14%] py-1.5 text-right font-normal">
                      Peak sales
                    </th>
                    <th
                      className="w-[9%] py-1.5 text-right font-normal"
                      title="Probability of reaching market"
                    >
                      PoS
                    </th>
                    <th
                      className="w-[9%] py-1.5 text-right font-normal"
                      title="Loss of exclusivity"
                    >
                      LOE
                    </th>
                    <th className="w-[15%] py-1.5 text-right font-normal">
                      rNPV
                    </th>
                    <th className="w-[12%] py-1.5 text-right font-normal">
                      Share
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.assets.map((asset) => (
                    <AssetRow
                      key={asset.name}
                      asset={asset}
                      share={total ? (asset.rnpv ?? 0) / total : null}
                      drug={
                        drugs.find((d) => d.id === asset.provenance?.id) ?? null
                      }
                      open={open === asset.name}
                      busy={busy}
                      onToggle={() =>
                        setOpen(open === asset.name ? null : asset.name)
                      }
                      onEdit={edit}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <Unvalued assets={result.unvalued} />

          {result.excluded.length > 0 && (
            <p className="font-data-sm text-[10px] text-on-surface-variant">
              Excluded from the total: {result.excluded.join(", ")}.
            </p>
          )}

          {result.sensitivity && (
            <Sensitivity grid={result.sensitivity} rate={discountRate} />
          )}

          <p className="border-t border-outline-variant pt-2 font-data-sm text-[10px] leading-relaxed text-on-surface-variant">
            {result.method} Clinical risk sits in each drug's probability, so
            the discount rate must not also carry a risk premium.
          </p>
        </>
      )}
    </TerminalPanel>
  );
}

/** Value per share, and the waterfall that produces it. */
function Headline({ result }: { result: ValuationResponse }) {
  if (result.equity_value === null) {
    return (
      <div className="rounded-2xl border border-outline-variant bg-surface p-4">
        <p className="font-data-tabular text-[16px] text-on-surface">
          No company value shown
        </p>
        <p className="mt-1 font-data-sm text-[10px] text-on-surface-variant">
          Net cash of {formatUSD(result.net_cash)} is on file, but no drug could
          be valued, so there is no total to report.
        </p>
      </div>
    );
  }
  const steps: [string, number][] = [
    ["Drug value", result.asset_value ?? 0],
    ["Corporate overhead", -result.overhead_present_value],
    ["Net cash", result.net_cash],
    ["Equity value", result.equity_value],
  ];
  return (
    <div className="rounded-2xl border border-primary/50 bg-primary/5 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-label-caps text-[9px] uppercase text-primary">
          Value per share
        </span>
        <span className="font-data-tabular text-[22px] font-bold text-primary">
          {result.value_per_share === null
            ? "—"
            : formatPrice(result.value_per_share)}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {steps.map(([label, amount], index) => (
          <div key={label}>
            <p className="font-label-caps text-[9px] uppercase text-on-surface-variant">
              {label}
            </p>
            <p
              className={`mt-0.5 font-data-tabular text-[12px] ${
                index === steps.length - 1
                  ? "font-bold text-on-surface"
                  : "text-on-surface"
              }`}
            >
              {amount < 0 ? `(${formatUSD(-amount)})` : formatUSD(amount)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function AssetRow({
  asset,
  share,
  drug,
  open,
  busy,
  onToggle,
  onEdit,
}: {
  asset: ValuedAsset;
  share: number | null;
  drug: DrugAsset | null;
  open: boolean;
  busy: boolean;
  onToggle: () => void;
  onEdit: (id: number, payload: Parameters<typeof api.updateDrug>[1]) => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className="cursor-pointer border-b border-outline-variant/50 text-on-surface hover:bg-surface-container-low"
      >
        <td className="py-1.5">
          <span className="flex items-center gap-1">
            <Icon
              name={open ? "expand_more" : "chevron_right"}
              size="xs"
              className="shrink-0 text-outline"
            />
            <span className="truncate" title={asset.name}>
              {asset.name}
            </span>
          </span>
        </td>
        <td className="py-1.5">
          <Badge
            className={`max-w-full truncate ${KIND_STYLE[asset.kind] ?? ""}`}
          >
            {asset.kind === "pipeline"
              ? phaseLabel(asset.provenance?.phase ?? null)
              : asset.kind}
          </Badge>
        </td>
        <td className="py-1.5 text-right font-data-tabular">
          {formatUSD(asset.peak_revenue)}
        </td>
        <td className="py-1.5 text-right font-data-tabular">
          {formatPct(asset.probability, 0)}
        </td>
        <td className="py-1.5 text-right font-data-tabular">
          {asset.loe_year ?? "—"}
        </td>
        <td className="py-1.5 text-right font-data-tabular">
          {formatUSD(asset.rnpv)}
        </td>
        <td className="py-1.5 text-right font-data-tabular">
          {formatPct(share, 0)}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="bg-surface-container-low p-3">
            <div className="max-w-full overflow-x-auto">
              <Drawer asset={asset} drug={drug} busy={busy} onEdit={onEdit} />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** Everything behind one drug: its quotes, where each input came from, and the model. */
function Drawer({
  asset,
  drug,
  busy,
  onEdit,
}: {
  asset: ValuedAsset;
  drug: DrugAsset | null;
  busy: boolean;
  onEdit: (id: number, payload: Parameters<typeof api.updateDrug>[1]) => void;
}) {
  const provenance = asset.provenance;
  const values = (provenance?.values ?? {}) as Record<string, unknown>;
  const quotes = [
    ["Exclusivity", values.loe_quote],
    ["Patient population", values.population_quote],
    ["Pipeline programme", values.pipeline_quote],
  ].filter(([, quote]) => typeof quote === "string" && quote) as [
    string,
    string,
  ][];
  const caveats = Array.isArray(values.loe_caveats)
    ? (values.loe_caveats as string[])
    : [];
  const warning = typeof values.warning === "string" ? values.warning : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {provenance?.indication && (
          <span className="font-data-sm text-[10px] text-on-surface-variant">
            {provenance.indication}
          </span>
        )}
        {Object.entries(provenance?.sources ?? {}).map(([field, source]) => (
          <Badge
            key={field}
            className={PROVENANCE_STYLE[source]}
            title={PROVENANCE_LABEL[source]}
          >
            {field.replace(/_/g, " ")}: {source.replace("_", " ")}
          </Badge>
        ))}
      </div>

      {warning && (
        <p className="font-data-sm text-[10px] text-caution">{warning}</p>
      )}
      {provenance?.loe_note && (
        <p className="font-data-sm text-[10px] text-caution">
          {provenance.loe_note}
        </p>
      )}

      {quotes.map(([label, quote]) => (
        <blockquote
          key={label}
          className="border-l-2 border-outline-variant pl-2 font-data-sm text-[10px] italic text-on-surface-variant"
        >
          <span className="not-italic uppercase tracking-wide">{label}: </span>“
          {quote}”
        </blockquote>
      ))}
      {caveats.map((caveat) => (
        <p
          key={caveat}
          className="font-data-sm text-[10px] text-on-surface-variant"
        >
          {caveat}
        </p>
      ))}

      {drug && <Overrides drug={drug} busy={busy} onEdit={onEdit} />}

      {asset.years.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-data-tabular text-[9px]">
            <thead className="text-on-surface-variant">
              <tr className="text-right">
                <th className="py-1 text-left font-normal">Year</th>
                {asset.years.map((year) => (
                  <th key={year.year} className="px-1 py-1 font-normal">
                    {year.year}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["Revenue", "revenue"],
                  ["Cash flow", "cash_flow"],
                  ["Risk-weighted", "risked_cash_flow"],
                  ["Present value", "present_value"],
                ] as const
              ).map(([label, key]) => (
                <tr
                  key={key}
                  className="border-t border-outline-variant/40 text-right"
                >
                  <th className="py-1 text-left font-normal text-on-surface-variant">
                    {label}
                  </th>
                  {asset.years.map((year) => (
                    <td key={year.year} className="px-1 py-1 text-on-surface">
                      {formatUSD(year[key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Inline edits. Blank means "keep what the filing said". */
function Overrides({
  drug,
  busy,
  onEdit,
}: {
  drug: DrugAsset;
  busy: boolean;
  onEdit: (id: number, payload: Parameters<typeof api.updateDrug>[1]) => void;
}) {
  const shown = (field: (typeof OVERRIDE_FIELDS)[number]) => {
    const raw = drug.overrides[field.key] ?? drug.extracted[field.key];
    if (typeof raw !== "number") return "";
    return field.kind === "pct" ? String(+(raw * 100).toFixed(1)) : String(raw);
  };
  const commit = (field: (typeof OVERRIDE_FIELDS)[number], text: string) => {
    if (text === "" || Number.isNaN(Number(text))) return;
    const parsed = field.kind === "pct" ? Number(text) / 100 : Number(text);
    if (parsed === (drug.overrides[field.key] ?? drug.extracted[field.key]))
      return;
    onEdit(drug.id, { overrides: { [field.key]: parsed } });
  };

  return (
    <div className="rounded-sm border border-outline-variant bg-surface p-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="font-label-caps text-[9px] uppercase text-on-surface-variant">
          Adjust this drug
        </span>
        <span className="flex gap-2 font-data-sm text-[10px]">
          {Object.keys(drug.overrides).length > 0 && (
            <button
              disabled={busy}
              onClick={() => onEdit(drug.id, { reset_overrides: true })}
              className="text-primary hover:underline disabled:opacity-40"
            >
              Reset to filing
            </button>
          )}
          <button
            disabled={busy}
            onClick={() => onEdit(drug.id, { included: !drug.included })}
            className="text-primary hover:underline disabled:opacity-40"
          >
            {drug.included ? "Exclude" : "Include"}
          </button>
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {OVERRIDE_FIELDS.map((field) => (
          <label key={field.key} className="block">
            <span className="font-data-sm text-[9px] uppercase text-on-surface-variant">
              {field.label}
              {field.kind === "pct" && " %"}
            </span>
            <input
              type="number"
              disabled={busy}
              defaultValue={shown(field)}
              key={`${field.key}-${shown(field)}`}
              onBlur={(e) => commit(field, e.target.value)}
              className="mt-0.5 w-full rounded-sm border border-outline-variant bg-background px-1.5 py-1 font-data-tabular text-data-tabular text-on-surface outline-none disabled:opacity-40"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

/** Programmes we will not put a number on, and why. */
function Unvalued({ assets }: { assets: ValuedAsset[] }) {
  if (!assets.length) return null;
  return (
    <details className="rounded-sm border border-outline-variant bg-surface p-2">
      <summary className="cursor-pointer font-data-sm text-[10px] text-on-surface-variant">
        {assets.length} programme{assets.length === 1 ? "" : "s"} carried at no
        value
      </summary>
      <ul className="mt-2 space-y-1.5">
        {assets.map((asset) => (
          <li key={asset.name} className="font-data-sm text-[10px]">
            <span className="text-on-surface">{asset.name}</span>
            {asset.provenance?.phase && (
              <span className="text-on-surface-variant">
                {" "}
                · {phaseLabel(asset.provenance.phase)}
              </span>
            )}
            {asset.unvalued_reason && (
              <span className="block text-on-surface-variant">
                {asset.unvalued_reason}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Value per share across discount rates and a proportional shift in every drug's sales. */
function Sensitivity({
  grid,
  rate,
}: {
  grid: NonNullable<ValuationResponse["sensitivity"]>;
  rate: number;
}) {
  const flat = grid.value_per_share
    .flat()
    .filter((v): v is number => v !== null);
  if (!flat.length) return null;
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const baseRow = grid.discount_rates.reduce(
    (best, value, index) =>
      Math.abs(value - rate) < Math.abs(grid.discount_rates[best] - rate)
        ? index
        : best,
    0,
  );
  const baseCol = grid.revenue_multipliers.indexOf(1);
  const shade = (v: number) => {
    if (max === min) return "rgba(56,225,198,0.15)";
    const t = (v - min) / (max - min);
    return t >= 0.5
      ? `rgba(56,225,198,${0.08 + 0.4 * (t - 0.5) * 2})`
      : `rgba(255,180,171,${0.08 + 0.4 * (0.5 - t) * 2})`;
  };

  return (
    <div>
      <span className="mb-1 block font-label-caps text-label-caps uppercase text-on-surface-variant">
        Discount rate × sales
      </span>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-data-tabular text-[9px]">
          <thead>
            <tr className="text-on-surface-variant">
              <th className="bg-surface-container p-1 font-normal" />
              {grid.revenue_multipliers.map((multiplier, column) => (
                <th
                  key={multiplier}
                  className={`bg-surface-container p-1 font-normal ${column === baseCol ? "text-primary" : ""}`}
                >
                  {multiplier.toFixed(1)}×
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.value_per_share.map((row, i) => (
              <tr key={grid.discount_rates[i]}>
                <td
                  className={`bg-surface-container p-1 text-on-surface-variant ${i === baseRow ? "text-primary" : ""}`}
                >
                  {formatPct(grid.discount_rates[i], 0)}
                </td>
                {row.map((cell, j) => (
                  <td
                    key={grid.revenue_multipliers[j]}
                    className={`p-1 text-center text-on-surface ${
                      i === baseRow && j === baseCol
                        ? "font-bold text-primary ring-1 ring-inset ring-primary"
                        : ""
                    }`}
                    style={{
                      backgroundColor:
                        cell === null ? "transparent" : shade(cell),
                    }}
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
