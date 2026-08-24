import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CompanySummary, Meta, Metric } from "../types";
import CompanyHeader from "../components/CompanyHeader";
import FinancialTable from "../components/FinancialTable";
import ValuationPanel from "../components/ValuationPanel";
import CatalystTimeline from "../components/CatalystTimeline";
import SignalPanel from "../components/SignalPanel";
import AnalystPanel from "../components/AnalystPanel";
import { ErrorNote, Icon, Spinner } from "../components/ui";

export default function Dashboard({ ticker, meta }: { ticker: string | null; meta: Meta | null }) {
  const [summary, setSummary] = useState<CompanySummary | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const analystProvider = meta?.analyst_provider ?? null;

  return (
    <div className="grid auto-rows-min grid-cols-12 gap-2">
      <div className="col-span-12">
        <CompanyHeader summary={summary} />
      </div>

      <div className="col-span-12 h-[360px] xl:col-span-4">
        <SignalPanel ticker={ticker} className="h-full" />
      </div>
      <div className="col-span-12 h-[360px] xl:col-span-4">
        <AnalystPanel ticker={ticker} analystProvider={analystProvider} className="h-full" />
      </div>
      <div className="col-span-12 h-[360px] xl:col-span-4">
        <ValuationPanel ticker={ticker} className="h-full" />
      </div>

      <div className="col-span-12 h-[340px] xl:col-span-8">
        <FinancialTable metrics={metrics} className="h-full" />
      </div>
      <div className="col-span-12 h-[340px] xl:col-span-4">
        <CatalystTimeline
          ticker={ticker}
          catalystProvider={meta?.catalyst_provider ?? null}
          className="h-full"
        />
      </div>
    </div>
  );
}
