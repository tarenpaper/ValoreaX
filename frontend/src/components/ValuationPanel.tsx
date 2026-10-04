import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  DrugAsset,
  Provenance,
  ValuationResponse,
  ValuedAsset,
} from "../types";
import { formatPct, formatPrice, formatUSD } from "../format";
import { Badge, ErrorNote, Icon, Spinner } from "./ui";
import ValuationOverview from "./ValuationOverview";
import "./valuation.css";

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
  { key: "probability", label: "Chance of reaching market", kind: "pct" },
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
  const [automatic, setAutomatic] = useState(true);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [discountRate, setDiscountRate] = useState(DEFAULT_DISCOUNT_RATE);
  const [status, setStatus] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [section, setSection] = useState<"drugs" | "assumptions">("drugs");
  const [kind, setKind] = useState("all");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestVersion = useRef(0);

  const value = useCallback(
    async (rate: number | null, includeSensitivity = false) => {
      const version = ++requestVersion.current;
      const [valuation, listing] = await Promise.all([
        api.valuation(ticker, { discount_rate: rate, include_sensitivity: includeSensitivity }),
        api.drugs(ticker),
      ]);
      if (version !== requestVersion.current) return;
      setAutomatic(rate === null);
      setDiscountRate(valuation.discount_rate);
      if (!includeSensitivity) onChangeRef.current?.(valuation.discount_rate);
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
    setKind("all");
    setSection("drugs");
    setStatus("Reading the latest 10-K…");
    (async () => {
      try {
        const sync = await api.syncDrugs(ticker);
        if (!active) return;
        setWarnings(sync.warnings);
        setStatus("Valuing each drug…");
        await value(null);
      } catch (e) {
        if (active) setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        if (active) setStatus(null);
      }
    })();
    return () => {
      active = false;
      requestVersion.current += 1;
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // The discount rate re-values through `revalue`, not by rebuilding the models.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current); }, []);

  const revalue = (rate: number) => {
    if (!Number.isFinite(rate) || rate < 0.01 || rate > 0.5) return;
    setError(null);
    setAutomatic(false);
    setDiscountRate(rate);
    setBusy(true);
    requestVersion.current += 1;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setBusy(true);
      try {
        await value(rate);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    }, 400);
  };

  const edit = async (
    id: number,
    payload: Parameters<typeof api.updateDrug>[1],
  ) => {
    setBusy(true);
    setError(null);
    try {
      await api.updateDrug(id, payload);
      await value(automatic ? null : discountRate);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      throw e;
    } finally {
      setBusy(false);
    }
  };

  const total = result?.asset_value ?? 0;
  const sortedAssets = [...(result?.assets ?? [])].sort((a, b) => (b.rnpv ?? 0) - (a.rnpv ?? 0));
  const visibleAssets = sortedAssets.filter(asset => kind === "all" || asset.kind === kind);
  const maxAsset = Math.max(1, ...sortedAssets.map(asset => Math.abs(asset.rnpv ?? 0)));

  async function restoreAutomatic() {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setBusy(true); setError(null);
    try { await value(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <section className={`terminal-panel valuation-panel min-w-0 overflow-hidden border border-outline-variant/50 ${className}`} aria-label="Sum-of-the-parts valuation">
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-6 sm:px-6">
        <div className="min-w-0">
          <p className="valuation-eyebrow">VALUATION WORKSPACE</p>
          <h2 className="mt-1 text-lg font-semibold tracking-tight">Sum-of-the-parts valuation</h2>
          <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">Each drug's future cash flows, brought together.</p>
        </div>
        <span role="status" aria-live="polite" className="flex items-center gap-1.5 rounded-full bg-surface-container px-3 py-1.5 text-xs text-on-surface-variant">
          <Icon name={busy || status ? "sync" : "functions"} size="xs" />
          {busy ? "Updating…" : status ? "Building model…" : "Risk-adjusted model"}
        </span>
      </header>
      <div className="min-w-0 space-y-5 p-5 sm:p-6">
        {error && <ErrorNote message={error} />}
        {status && !result && <div className="rounded-2xl bg-surface-container-low p-6"><Spinner label={status} /></div>}
        {result && <>
          <ValuationOverview result={result} busy={busy} />
          <button type="button" onClick={() => setSection("assumptions")} className="flex w-full flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-container-low px-4 py-3 text-left text-xs hover:bg-surface-container focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
            <span className="flex items-center gap-2"><Icon name="tune" size="xs" /><span>Discount rate <strong className="font-mono text-on-surface">{formatPct(discountRate, 2)}</strong> · {automatic ? result.wacc.status === "fallback" ? "Automatic · fallback" : "Automatic WACC" : "Manual override"}</span></span>
            <span className="flex items-center gap-1 text-primary">Review assumptions <Icon name="arrow_forward" size="xs" /></span>
          </button>
          <div className="valuation-view-switch" role="group" aria-label="Valuation view">
            <button type="button" aria-pressed={section === "drugs"} onClick={() => setSection("drugs")}>Drug breakdown <span>{result.assets.length}</span></button>
            <button type="button" aria-pressed={section === "assumptions"} onClick={() => setSection("assumptions")}>Assumptions & scenarios</button>
          </div>
          {section === "drugs" && <div className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div><h3 className="text-sm font-semibold">What drives the drug value</h3><p className="mt-1 text-xs text-on-surface-variant">Largest modeled values first. Open a drug to inspect or edit.</p></div>
              <label className="flex items-center gap-2 text-xs text-on-surface-variant">Show
                <select aria-label="Filter drug contributions" value={kind} onChange={event => setKind(event.target.value)} className="rounded-lg border border-outline-variant bg-surface px-2 py-2 text-on-surface focus-visible:outline-primary">
                  <option value="all">All drugs</option><option value="marketed">Marketed</option><option value="pipeline">Pipeline</option><option value="royalty">Royalties</option>
                </select>
              </label>
            </div>
            {visibleAssets.length > 0 ? <div className="valuation-asset-list" tabIndex={0} role="region" aria-label="Drug value contributions, scroll for more drugs">
              {visibleAssets.map(asset => <AssetCard key={asset.provenance?.id ?? asset.name} asset={asset}
                share={total > 0 ? (asset.rnpv ?? 0) / total : null} maxAsset={maxAsset}
                drug={drugs.find(drug => drug.id === asset.provenance?.id) ?? null}
                open={open === asset.name} busy={busy}
                onToggle={() => setOpen(open === asset.name ? null : asset.name)} onEdit={edit} />)}
            </div> : <div className="rounded-2xl border border-dashed border-outline-variant p-6 text-center text-sm text-on-surface-variant">
              {result.assets.length ? "No drugs in this category. Choose another filter." : "No drugs have enough inputs to be valued yet. Review the missing inputs below."}
            </div>}
            {sortedAssets.some(asset => (asset.rnpv ?? 0) < 0) && <p className="text-xs text-on-surface-variant">Bars compare absolute drug values. Negative values reduce the total.</p>}
            <Unvalued assets={result.unvalued} drugs={drugs} busy={busy} onEdit={edit} />
            {result.excluded.length > 0 && <details className="valuation-disclosure">
              <summary>{result.excluded.length} excluded drug{result.excluded.length === 1 ? "" : "s"}</summary>
              <p className="mt-3 text-xs text-on-surface-variant">These drugs do not contribute to the current total.</p>
              <ul className="mt-3 space-y-2">{result.excluded.map(name => {
                const drug = drugs.find(drug => drug.name === name && !drug.included);
                return <li key={name} className="flex items-center justify-between gap-3 text-sm"><span>{name}</span>{drug && <button type="button" disabled={busy} onClick={() => { void edit(drug.id, { included: true }).catch(() => {}); }} className="valuation-text-button">Include in model</button>}</li>;
              })}</ul>
            </details>}
          </div>}
          {section === "assumptions" && <div className="space-y-5">
            <div className="valuation-assumptions rounded-2xl border border-outline-variant p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><h3 className="text-sm font-semibold">Discounting future cash flows</h3><p className="mt-1 max-w-lg text-xs leading-relaxed text-on-surface-variant">Use the company’s estimated weighted average cost of capital (WACC), or explore your own rate.</p></div>
                <label className="text-xs text-on-surface-variant">Discount rate (%)<input type="number" step={0.5} min={1} max={50} disabled={!!status} value={+(discountRate * 100).toFixed(1)} onChange={event => revalue(Number(event.target.value) / 100)} className="mt-1 block w-24 rounded-xl border border-outline-variant bg-background px-3 py-2 font-mono text-sm text-on-surface focus-visible:outline-primary" /></label>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-container-low p-3 text-xs">
                <span>{result.wacc.status === "fallback" ? "Fallback rate" : "Estimated company WACC"}: <strong>{formatPct(result.wacc.rate, 2)}</strong></span>
                {!automatic ? <button type="button" disabled={busy} className="valuation-text-button" onClick={restoreAutomatic}>Use automatic WACC</button> : <span className="text-primary">Automatic rate applied</span>}
              </div>
              <details className="mt-4 text-xs text-on-surface-variant"><summary className="cursor-pointer font-medium text-on-surface">How WACC is calculated</summary>
                <p className="mt-3 leading-relaxed">WACC = equity weight × cost of equity + debt weight × cost of debt × (1 − tax rate).</p>
                <dl className="valuation-wacc-grid mt-4">
                  <WaccFact label="Risk-free rate" value={formatPct(result.wacc.risk_free_rate, 2)} note={`${result.wacc.risk_free_source}${result.wacc.risk_free_as_of ? ` · ${result.wacc.risk_free_as_of}` : ""}`} />
                  <WaccFact label="Beta" value={result.wacc.beta.toFixed(2)} note={`${result.wacc.beta_source} · ${result.wacc.beta_observations} returns`} />
                  <WaccFact label="Equity risk premium" value={formatPct(result.wacc.equity_risk_premium, 1)} note="Assumed" />
                  <WaccFact label="Cost of equity" value={formatPct(result.wacc.cost_of_equity, 2)} />
                  <WaccFact label="Cost of debt" value={formatPct(result.wacc.cost_of_debt, 2)} note={result.wacc.debt_source} />
                  <WaccFact label="Tax shield rate" value={formatPct(result.wacc.tax_rate, 0)} />
                  <WaccFact label="Equity / debt weights" value={result.wacc.equity_weight == null || result.wacc.debt_weight == null ? "Unavailable" : `${formatPct(result.wacc.equity_weight, 1)} / ${formatPct(result.wacc.debt_weight, 1)}`} />
                  <WaccFact label="Market equity / book debt" value={`${formatUSD(result.wacc.market_equity)} / ${formatUSD(result.wacc.book_debt)}`} />
                </dl>
                <p className="mt-3">Financial year: {result.wacc.fiscal_year ?? "Unavailable"} · Price date: {result.wacc.price_as_of ?? "Unavailable"}</p>
              </details>
              {result.wacc.warnings.length > 0 && <ul className="mt-4 space-y-2 border-t border-outline-variant pt-3 text-xs leading-relaxed text-caution">{result.wacc.warnings.map((note, i) => <li key={i}>{note}</li>)}</ul>}
            </div>
            <div className="rounded-2xl border border-outline-variant p-4 sm:p-5">
              <div className="mb-4"><h3 className="text-sm font-semibold">Explore different outcomes</h3><p className="mt-1 text-xs leading-relaxed text-on-surface-variant">See how value per share changes when discount rates and drug sales change together.</p></div>
              {!result.sensitivity ? <button type="button" disabled={busy || !!status} className="valuation-primary-button" onClick={async () => {
                setBusy(true); setError(null);
                try { await value(automatic ? null : discountRate, true); }
                catch (e) { setError(e instanceof Error ? e.message : String(e)); }
                finally { setBusy(false); }
              }}><Icon name="grid_on" size="xs" />{busy ? "Calculating…" : "Calculate sensitivity"}</button> : <Sensitivity grid={result.sensitivity} rate={discountRate} />}
            </div>
            <details className="valuation-disclosure"><summary>Valuation methodology</summary><p className="mt-3 text-xs leading-relaxed text-on-surface-variant">{result.method} Clinical risk sits in each drug's probability, so the discount rate must not also carry a clinical risk premium.</p></details>
          </div>}
          {(result.note || warnings.length > 0) && <details className="valuation-disclosure">
            <summary>Data coverage & model notes <span className="text-caution">({warnings.length + (result.note ? 1 : 0)})</span></summary>
            <div className="mt-3 space-y-2 text-xs leading-relaxed text-on-surface-variant">{result.note && <p>{result.note}</p>}{warnings.map(warning => <p key={warning} className="text-caution">{warning}</p>)}</div>
          </details>}
          <p className="border-t border-outline-variant pt-4 text-[11px] leading-relaxed text-on-surface-variant">Model estimates depend on disclosed data and assumptions. Drug cash flows end with exclusivity; no terminal value is added.</p>
        </>}
      </div>
    </section>
  );
}

function WaccFact({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div><dt className="text-on-surface-variant">{label}</dt><dd className="mt-1 font-mono text-sm text-on-surface">{value}</dd>{note && <dd className="mt-1 text-[11px] leading-relaxed">{note}</dd>}</div>;
}

function AssetCard({ asset, share, maxAsset, drug, open, busy, onToggle, onEdit }: {
  asset: ValuedAsset; share: number | null; maxAsset: number; drug: DrugAsset | null;
  open: boolean; busy: boolean; onToggle: () => void;
  onEdit: (id: number, payload: Parameters<typeof api.updateDrug>[1]) => Promise<void>;
}) {
  const drawerId = `drug-model-${drug?.id ?? encodeURIComponent(asset.name)}`;
  return <article className="valuation-asset-card">
    <button type="button" aria-expanded={open} aria-controls={drawerId} onClick={onToggle} className="valuation-asset-toggle">
      <span className="valuation-asset-heading flex min-w-0 flex-wrap items-center justify-between gap-3">
        <span className="min-w-0 flex-1"><span className="block break-words text-sm font-semibold">{asset.name}</span><span className="mt-1.5 flex flex-wrap items-center gap-2"><Badge className={KIND_STYLE[asset.kind]}>{asset.kind === "pipeline" ? `Pipeline · ${phaseLabel(asset.provenance?.phase ?? null)}` : asset.kind}</Badge>{drug && Object.keys(drug.overrides).length > 0 && <span className="text-[10px] text-on-surface-variant">Edited assumptions</span>}</span></span>
        <span className="flex items-center gap-3"><span className="text-right"><span className={`block font-mono text-base font-semibold ${(asset.rnpv ?? 0) < 0 ? "text-caution" : "text-on-surface"}`}>{formatUSD(asset.rnpv)}</span><span className="mt-1 block text-[10px] text-on-surface-variant">{share == null ? "Risk-adjusted value" : `${formatPct(share, 1)} of drug value`}</span></span><Icon name={open ? "expand_less" : "expand_more"} size="base" /></span>
      </span>
      <span className="my-3 block h-1.5 overflow-hidden rounded-full bg-surface-container-high" aria-hidden="true"><span className={`block h-full rounded-full ${asset.kind === "pipeline" ? "bg-secondary" : asset.kind === "royalty" || (asset.rnpv ?? 0) < 0 ? "bg-caution" : "bg-primary"}`} style={{ width: `${Math.abs(asset.rnpv ?? 0) / maxAsset * 100}%` }} /></span>
      <span className="valuation-asset-stats"><span><span>Peak sales</span><strong>{formatUSD(asset.peak_revenue)}</strong></span><span><span>Market success</span><strong>{formatPct(asset.probability, 0)}</strong></span><span><span>Exclusivity ends</span><strong>{asset.loe_year ?? "—"}</strong></span></span>
    </button>
    {open && <div id={drawerId} className="border-t border-outline-variant p-4"><Drawer asset={asset} drug={drug} busy={busy} onEdit={onEdit} /></div>}
  </article>;
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
  onEdit: (id: number, payload: Parameters<typeof api.updateDrug>[1]) => Promise<void>;
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
    <div className="space-y-4">
      {drug && <Overrides key={`${drug.id}-${JSON.stringify(drug.overrides)}-${JSON.stringify(drug.extracted)}`} drug={drug} busy={busy} onEdit={onEdit} />}
      <details className="valuation-disclosure"><summary>Sources & filing evidence</summary>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {provenance?.indication && (
          <span className="text-xs text-on-surface-variant">
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
        <p className="text-xs text-caution">{warning}</p>
      )}
      {provenance?.loe_note && (
        <p className="text-xs text-caution">
          {provenance.loe_note}
        </p>
      )}

      {quotes.map(([label, quote]) => (
        <blockquote
          key={label}
          className="border-l-2 border-outline-variant pl-2 text-xs italic text-on-surface-variant"
        >
          <span className="not-italic uppercase tracking-wide">{label}: </span>“
          {quote}”
        </blockquote>
      ))}
      {caveats.map((caveat) => (
        <p
          key={caveat}
          className="text-xs text-on-surface-variant"
        >
          {caveat}
        </p>
      ))}

      </details>

      {asset.years.length > 0 && <details className="valuation-disclosure"><summary>Annual cash flow projections</summary>
        <div className="mt-3 overflow-x-auto" tabIndex={0} role="region" aria-label={`${asset.name} annual cash flow projections`}>
          <table className="w-full border-collapse whitespace-nowrap text-right text-xs"><caption className="pb-3 text-left text-xs text-on-surface-variant">Projected drug cash flows in USD. Risk-weighted cash flow includes the probability of reaching market.</caption>
            <thead className="text-on-surface-variant"><tr><th scope="col" className="p-2 text-left font-medium">Year</th><th scope="col" className="p-2 font-medium">Revenue</th><th scope="col" className="p-2 font-medium">Cash flow</th><th scope="col" className="p-2 font-medium">Risk-weighted</th><th scope="col" className="p-2 font-medium">Present value</th></tr></thead>
            <tbody>{asset.years.map(year => <tr key={year.year} className="border-t border-outline-variant"><th scope="row" className="p-2 text-left font-mono font-normal">{year.year}</th>{(["revenue", "cash_flow", "risked_cash_flow", "present_value"] as const).map(field => <td key={field} className="p-2 font-mono">{formatUSD(year[field])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </details>}
    </div>
  );
}

/** Edits save together; all currency inputs use full USD amounts. */
function Overrides({ drug, busy, onEdit }: {
  drug: DrugAsset; busy: boolean;
  onEdit: (id: number, payload: Parameters<typeof api.updateDrug>[1]) => Promise<void>;
}) {
  const original = Object.fromEntries(OVERRIDE_FIELDS.map(field => {
    const raw = drug.overrides[field.key] ?? drug.extracted[field.key];
    return [field.key, typeof raw === "number" ? String(field.kind === "pct" ? +(raw * 100).toFixed(1) : raw) : ""];
  }));
  const [draft, setDraft] = useState(original);
  const changed = OVERRIDE_FIELDS.some(field => draft[field.key] !== original[field.key]);
  return <form className="rounded-2xl bg-surface-container-low p-4" onSubmit={async event => {
    event.preventDefault();
    const overrides: Record<string, number> = {};
    for (const field of OVERRIDE_FIELDS) {
      if (draft[field.key] === "" || draft[field.key] === original[field.key]) continue;
      overrides[field.key] = Number(draft[field.key]) / (field.kind === "pct" ? 100 : 1);
    }
    if (!Object.keys(overrides).length) return;
    try { await onEdit(drug.id, { overrides }); }
    catch { /* The panel shows the error; retain the draft for retry. */ }
  }}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-semibold">Drug assumptions</h4><button type="button" disabled={busy} onClick={() => { void onEdit(drug.id, { included: !drug.included }).catch(() => {}); }} className="valuation-text-button">{drug.included ? "Exclude from model" : "Include in model"}</button></div>
    <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">Currency amounts are in full US dollars. Changes are applied when you save.</p>
    <div className="valuation-input-grid mt-4">{OVERRIDE_FIELDS.map(field => <label key={field.key} className="text-xs text-on-surface-variant">
      {field.label}{field.kind === "usd" ? " (USD)" : field.kind === "pct" ? " (%)" : ""}
      <input type="number" disabled={busy} value={draft[field.key]} min={field.kind === "year" ? 1990 : field.kind === "int" ? 1 : 0} max={field.kind === "pct" ? 100 : field.kind === "year" ? 2100 : field.kind === "int" ? 20 : undefined} step={field.kind === "year" || field.kind === "int" ? 1 : "any"} required={original[field.key] !== ""} placeholder="Not disclosed" onChange={event => setDraft(previous => ({ ...previous, [field.key]: event.target.value }))} className="mt-1.5 w-full min-w-0 rounded-lg border border-outline-variant bg-surface px-3 py-2 font-mono text-xs text-on-surface focus-visible:outline-primary disabled:opacity-50" />
    </label>)}</div>
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <span className="text-xs text-on-surface-variant" role="status">{busy ? "Applying changes…" : changed ? "Unsaved changes" : "Saved assumptions"}</span>
      <div className="flex flex-wrap items-center gap-3">{Object.keys(drug.overrides).length > 0 && <button type="button" disabled={busy} onClick={() => { void onEdit(drug.id, { reset_overrides: true }).catch(() => {}); }} className="valuation-text-button">Reset to filing</button>}<button type="submit" disabled={busy || !changed} className="valuation-primary-button">Save assumptions</button></div>
    </div>
  </form>;
}

function Unvalued({ assets, drugs, busy, onEdit }: { assets: ValuedAsset[]; drugs: DrugAsset[]; busy: boolean; onEdit: (id: number, payload: Parameters<typeof api.updateDrug>[1]) => Promise<void> }) {
  if (!assets.length) return null;
  return <details className="valuation-disclosure"><summary>{assets.length} programme{assets.length === 1 ? "" : "s"} without a standalone value</summary>
    <p className="mt-3 text-xs leading-relaxed text-on-surface-variant">These programmes do not contribute to the drug total. Any separate pipeline estimate is shown in the company breakdown above.</p>
    <div className="mt-3 space-y-3">{assets.map(asset => {
      const drug = drugs.find(drug => drug.id === asset.provenance?.id);
      return <div key={asset.name} className="rounded-xl bg-surface-container-low p-3"><p className="text-sm font-medium">{asset.name}</p><p className="mt-1 text-xs leading-relaxed text-on-surface-variant">{asset.provenance?.phase && `${phaseLabel(asset.provenance.phase)} · `}{asset.unvalued_reason ?? "Additional model inputs are needed."}</p>{drug && <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-primary">Review inputs</summary><div className="mt-3"><Overrides key={`${drug.id}-${JSON.stringify(drug.overrides)}`} drug={drug} busy={busy} onEdit={onEdit} /></div></details>}</div>;
    })}</div>
  </details>;
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
  if (!flat.length) return <p className="text-xs text-on-surface-variant">Sensitivity values are unavailable because the model has no value per share.</p>;
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
    if (max === min) return "rgb(var(--color-primary) / 0.15)";
    const t = (v - min) / (max - min);
    return t >= 0.5
      ? `rgb(var(--color-primary) / ${0.08 + 0.4 * (t - 0.5) * 2})`
      : `rgb(var(--color-caution) / ${0.08 + 0.4 * (0.5 - t) * 2})`;
  };

  return (
    <div>
      <span className="mb-1 block font-label-caps text-label-caps uppercase text-on-surface-variant">
        Value per share (USD)
      </span>
      <p className="mb-3 text-xs leading-relaxed text-on-surface-variant">Columns scale drug sales; rows change the discount rate. The outlined cell is the closest rate to your current model with unchanged sales.</p>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Valuation sensitivity table">
        <table className="w-full min-w-[320px] border-collapse font-mono text-xs">
          <thead>
            <tr className="text-on-surface-variant">
              <th scope="col" className="bg-surface-container p-2 text-left font-sans text-[11px] font-normal">Rate / sales</th>
              {grid.revenue_multipliers.map((multiplier, column) => (
                <th
                  key={multiplier}
                  className={`bg-surface-container p-2 font-normal ${column === baseCol ? "text-primary" : ""}`}
                >
                  {multiplier.toFixed(1)}×
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.value_per_share.map((row, i) => (
              <tr key={grid.discount_rates[i]}>
                <th scope="row"
                  className={`bg-surface-container p-2 font-normal text-on-surface-variant ${i === baseRow ? "text-primary" : ""}`}
                >
                  {formatPct(grid.discount_rates[i], 1)}
                </th>
                {row.map((cell, j) => (
                  <td
                    key={grid.revenue_multipliers[j]}
                    className={`p-2 text-center text-on-surface ${
                      i === baseRow && j === baseCol
                        ? "font-bold text-primary ring-1 ring-inset ring-primary"
                        : ""
                    }`}
                    style={{
                      backgroundColor:
                        cell === null ? "transparent" : shade(cell),
                    }}
                  >
                    {cell === null ? "—" : formatPrice(cell)}
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
