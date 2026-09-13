import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CompanySummary, Meta, Metric } from "../types";
import ResearchPanel from "../components/ResearchPanel";
import CompanyHeader from "../components/CompanyHeader";
import FinancialTable from "../components/FinancialTable";
import ValuationPanel, { DEFAULT_ASSUMPTIONS } from "../components/ValuationPanel";
import CatalystTimeline from "../components/CatalystTimeline";
import SignalPanel from "../components/SignalPanel";
import AnalystPanel from "../components/AnalystPanel";
import { ErrorNote, Icon, Spinner } from "../components/ui";

export default function Dashboard({ ticker, meta, focus = "dashboard" }: { ticker: string | null; meta: Meta | null; focus?: "dashboard" | "clinical" | "financials" }) {
  const [summary, setSummary] = useState<CompanySummary | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Shared so Plutus reasons about the same DCF the user is editing. Seeded with the
  // panel's own defaults so the first research call already includes the model.
  const [assumptions, setAssumptions] = useState<Record<string, number>>(DEFAULT_ASSUMPTIONS);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    setError(null);
    try {
      const [s, m] = await Promise.all([api.summary(t), api.metrics(t)]);
      setSummary(s);
      setMetrics(m.metrics);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ticker) load(ticker);
    else setSummary(null);
  }, [ticker, load]);

  if (!ticker) {
    return (
      <div className="grid h-full place-items-center text-center text-on-surface-variant">
        <div className="flex flex-col items-center gap-3">
          <Icon name="query_stats" className="text-4xl text-outline" size="base" />
          <p className="font-body-main text-lg text-on-surface">Select or load a company to begin.</p>
          <p className="font-data-sm text-data-sm">
            Search a ticker in the sidebar — any US filer loads live from SEC EDGAR.
          </p>
        </div>
      </div>
    );
  }

  if (loading && !summary) return <Spinner label={`Loading ${ticker}…`} />;
  if (error) return <ErrorNote message={error} />;
  if (!summary) return null;

  if (focus === "clinical") return <div className="space-y-7"><CompanyHeader summary={summary} /><ResearchPanel key={`clinical-${ticker}`} ticker={ticker} scope="clinical" /><CatalystTimeline ticker={ticker} catalystProvider={meta?.catalyst_provider ?? null} /></div>;
  if (focus === "financials") return <div className="space-y-7"><CompanyHeader summary={summary} /><ValuationPanel ticker={ticker} /><FinancialTable metrics={metrics} /></div>;

  const analystProvider = meta?.analyst_provider ?? null;

  return (
    <div className="space-y-7">
      <CompanyHeader summary={summary} />
      <ResearchPanel ticker={ticker} assumptions={assumptions} />
      <div className="grid items-start gap-6 xl:grid-cols-12">
        <div className="min-w-0 space-y-6 xl:col-span-7">
          <ValuationPanel ticker={ticker} className="min-h-[440px]" onAssumptions={setAssumptions} />
          <FinancialTable metrics={metrics} />
        </div>
        <div className="min-w-0 space-y-6 xl:col-span-5">
          <AnalystPanel ticker={ticker} analystProvider={analystProvider} className="max-h-[540px]" />
          <CatalystTimeline ticker={ticker} catalystProvider={meta?.catalyst_provider ?? null} />
          <SignalPanel ticker={ticker} />
        </div>
      </div>
    </div>
  );
}
