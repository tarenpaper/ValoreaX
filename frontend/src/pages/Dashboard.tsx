import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CompanySummary, Meta, Metric } from "../types";
import ResearchPanel from "../components/ResearchPanel";
import ClinicalMLPanel from "../components/ClinicalMLPanel";
import CompanyHeader from "../components/CompanyHeader";
import FinancialTable from "../components/FinancialTable";
import ValuationPanel from "../components/ValuationPanel";
import CatalystTimeline from "../components/CatalystTimeline";
import SignalPanel from "../components/SignalPanel";
import AnalystPanel from "../components/AnalystPanel";
import { ErrorNote, Icon, Spinner } from "../components/ui";

export default function Dashboard({ ticker, meta, focus = "dashboard" }: { ticker: string | null; meta: Meta | null; focus?: "dashboard" | "clinical" | "financials" }) {
  const [summary, setSummary] = useState<CompanySummary | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [clinicalRevision, setClinicalRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped whenever the drug models change, so Plutus re-reads the same valuation the
  // user is looking at rather than a stale one.
  const [valuationDiscountRate, setValuationDiscountRate] = useState<number | null>(null);
  const [valuationRevision, setValuationRevision] = useState(0);

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

  const header = summary
    ? <CompanyHeader summary={summary} />
    : loading
      ? <Spinner label={`Loading ${ticker}…`} />
      : error
        ? <ErrorNote message={error} />
        : null;

  if (focus === "clinical") return <div className="space-y-7">{header}<ClinicalMLPanel key={`ml-${ticker}`} ticker={ticker} onIngest={() => setClinicalRevision(value => value + 1)} /><ResearchPanel key={`clinical-${ticker}-${clinicalRevision}`} ticker={ticker} scope="clinical" /><CatalystTimeline ticker={ticker} catalystProvider={meta?.catalyst_provider ?? null} /></div>;
  if (focus === "financials") return <div className="space-y-7">{header}<ValuationPanel ticker={ticker} /><FinancialTable metrics={metrics} /></div>;

  const analystProvider = meta?.analyst_provider ?? null;

  return (
    <div className="space-y-7">
      {header}
      <ResearchPanel ticker={ticker} revision={valuationRevision} discountRate={valuationDiscountRate} />
      <div className="grid items-start gap-6 xl:grid-cols-12">
        <div className="min-w-0 space-y-6 xl:col-span-7">
          <ValuationPanel ticker={ticker} className="min-h-[440px]" onChange={rate => { setValuationDiscountRate(rate); setValuationRevision(value => value + 1); }} />
          <FinancialTable metrics={metrics} />
        </div>
        <div className="min-w-0 space-y-6 xl:col-span-5">
          <AnalystPanel ticker={ticker} analystProvider={analystProvider} className="max-h-[540px]" />
          <CatalystTimeline ticker={ticker} catalystProvider={meta?.catalyst_provider ?? null} className="max-h-[300px]" />
          <SignalPanel ticker={ticker} />
        </div>
      </div>
    </div>
  );
}
