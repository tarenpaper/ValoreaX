import type { BiotechProfile, CompanySummary, Metric } from "../types";
import { conceptLabel, formatFigure, formatUSD, statusColor } from "../format";

// Fallback headline when no biotech profile is available.
const TILES: Array<{ concept: string; label: string }> = [
  { concept: "revenue", label: "Revenue" },
  { concept: "ebitda", label: "EBITDA" },
  { concept: "operating_income", label: "Operating income" },
  { concept: "cash", label: "Cash & equiv." },
  { concept: "total_debt", label: "Total debt" },
  { concept: "shares_outstanding", label: "Shares out." },
];

const FIGURE_LABELS: Record<string, string> = {
  revenue: "Revenue",
  liquidity: "Liquidity",
  free_cash_flow: "Free cash flow",
  research_development: "R&D expense",
  quarterly_burn: "Quarterly burn",
  runway_quarters: "Cash runway",
  fcf_margin: "FCF margin",
  rd_intensity: "R&D intensity",
  rd_share_of_spend: "R&D share of spend",
  dilution_yoy: "Dilution (YoY)",
};

// Figures that are changes rather than shares, so a positive value shows "+".
const SIGNED_FIGURES = new Set(["dilution_yoy"]);

function sourceLabel(src: string | undefined): string {
  if (src === "sec_edgar") return "SEC";
  if (src === "derived") return "DERIVED";
  if (src === "mock") return "SAMPLE";
  return (src ?? "—").toUpperCase();
}

type TileProps = {
  label: string;
  value: string | null;
  status: string;
  source: string | undefined;
  confidence: number;
  note: string | null | undefined;
  inputs?: string[];
};

function Tile({ label, value, status, source, confidence, note, inputs = [] }: TileProps) {
  const missing = value === null || status === "missing";
  const notMeaningful = status === "not_meaningful";
  const chip = notMeaningful ? "NOT APPLICABLE" : missing ? "MISSING" : `${status === "estimated" ? "ESTIMATED" : sourceLabel(source)} · ${(confidence * 100).toFixed(0)}%`;
  const chipClass = notMeaningful
    ? statusColor("missing")
    : missing
      ? "border-error/30 bg-error/10 text-error"
      : statusColor(status);
  return (
    <div className="flex min-h-[138px] min-w-0 flex-col rounded-2xl bg-surface px-5 py-4 shadow-sm">
      <div className="mb-1 font-label-caps text-label-caps uppercase text-on-surface-variant">{label}</div>
      <div className="font-data-tabular text-[19px] text-on-surface">
        {notMeaningful ? <span className="text-on-surface-variant">N/A</span> : value === null ? <span className="text-on-surface-variant opacity-50">—</span> : value}
      </div>
      {(note || inputs.length > 0) && <details className="mt-3 text-xs leading-relaxed text-on-surface-variant">
        <summary className="cursor-pointer text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">{missing || notMeaningful ? "Why this value?" : "Calculation & sources"}<span className="sr-only"> for {label}</span></summary>
        {note && <p className="mt-2">{note}</p>}
        {inputs.length > 0 && <p className="mt-2">Inputs: {inputs.map(conceptLabel).join(", ")}.</p>}
        {!missing && !notMeaningful && <p className="mt-2">Confidence describes the source data, not the likelihood of a future outcome.</p>}
      </details>}
      <div className="mt-1 flex">
        <span className={`rounded-full px-2 py-1 font-data-sm text-[9px] ${chipClass}`}>{chip}</span>
      </div>
    </div>
  );
}

function ProfileTiles({ profile, keys = profile.headline }: { profile: BiotechProfile; keys?: string[] }) {
  return (
    <>
      {keys.map((key) => {
        const f = profile.figures[key];
        const shown = f && f.value !== null && f.status !== "not_meaningful" && f.status !== "missing";
        return (
          <Tile
            key={key}
            label={FIGURE_LABELS[key] ?? key}
            value={shown ? formatFigure(f.value, f.unit, SIGNED_FIGURES.has(key)) : null}
            status={f?.status ?? "missing"}
            source={f?.source}
            confidence={f?.confidence ?? 0}
            note={f?.note}
            inputs={f?.inputs}
          />
        );
      })}
    </>
  );
}

function MetricTiles({ metrics }: { metrics: Record<string, Metric> }) {
  return (
    <>
      {TILES.map(({ concept, label }) => {
        const m: Metric | undefined = metrics[concept];
        const present = m && m.value !== null && m.quality.status !== "missing";
        return (
          <Tile
            key={concept}
            label={label}
            value={present ? formatUSD(m.value, m.unit) : null}
            status={m?.quality.status ?? "missing"}
            source={m?.source}
            confidence={m?.quality.confidence ?? 0}
            note={m?.quality.note}
          />
        );
      })}
    </>
  );
}

export default function CompanyHeader({ summary }: { summary: CompanySummary }) {
  const c = summary.company;
  const km = summary.key_metrics;
  const profile = summary.biotech_profile;
  const filingDate = km.revenue?.period_end ?? km.cash?.period_end ?? null;
  const isLive = c.source === "sec_edgar";

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-6 rounded-3xl bg-surface p-7 shadow-sm">
        <div className="flex items-center gap-5">
          <div className="hidden h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-surface-container font-editorial text-3xl sm:flex">{c.ticker.slice(0, 2)}</div>
          <div><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-semibold">{c.exchange ? `${c.exchange.toUpperCase()}: ` : ""}{c.ticker}</span><span className="rounded-full bg-surface-container px-3 py-1 text-[10px] font-semibold uppercase tracking-wide">{c.sector || "Healthcare"}</span><span className="rounded-full bg-primary/10 px-3 py-1 text-[10px] font-semibold text-primary">{isLive ? "SEC sourced" : "Sample company"}</span></div>
          <h2 className="mt-2 font-editorial text-3xl tracking-tight lg:text-4xl">{c.name}</h2><p className="mt-1 text-xs text-on-surface-variant">{c.industry || "Company research and intelligence"}{c.cik ? ` · CIK ${c.cik}` : ""}</p></div>
        </div>
        <div className="rounded-2xl bg-surface-container-low px-5 py-3"><p className="font-mono text-sm font-medium">{summary.latest_fiscal_year ? `FY ${summary.latest_fiscal_year}` : "Financial snapshot"}</p><p className="mt-1 text-xs text-on-surface-variant">{filingDate ? `Period ending ${filingDate}` : "No filings available"}</p></div>
      </div>

      {profile && (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2 rounded-2xl border border-outline-variant bg-surface-container-low px-4 py-3">
          <span className="rounded-full bg-secondary-container/30 px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-secondary">{profile.stage_label}</span>
          <p className="text-sm text-on-surface-variant">{profile.stage_reason}</p>
          <p className="w-full text-xs text-on-surface-variant">{profile.fiscal_year ? `FY ${profile.fiscal_year} · ` : ""}Six headline figures selected for this company’s stage.</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {profile ? <ProfileTiles profile={profile} /> : <MetricTiles metrics={km} />}
      </div>

      {profile && Object.keys(profile.figures).some(key => !profile.headline.includes(key)) && <details className="rounded-2xl border border-outline-variant bg-surface-container-low p-4">
        <summary className="cursor-pointer text-sm font-medium text-primary">More cash-flow and financing figures</summary>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ProfileTiles profile={profile} keys={Object.keys(profile.figures).filter(key => !profile.headline.includes(key))} />
        </div>
      </details>}

      {summary.data_quality_warnings.length > 0 && (
        <div className="border-t border-outline-variant px-4 py-2">
          <ul className="flex flex-wrap gap-x-4 font-data-sm text-data-sm text-caution">
            {summary.data_quality_warnings.map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
