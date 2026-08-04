import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CompanySummary, Metric } from "../types";
import CompanyHeader from "../components/CompanyHeader";
import FinancialTable from "../components/FinancialTable";
import ValuationPanel from "../components/ValuationPanel";
import CatalystTimeline from "../components/CatalystTimeline";
import SignalPanel from "../components/SignalPanel";
import { ErrorNote, Panel, Spinner } from "../components/ui";

export default function Dashboard({ ticker }: { ticker: string | null }) {
  const [summary, setSummary] = useState<CompanySummary | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signalNonce, setSignalNonce] = useState(0);

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
      <div className="grid h-full place-items-center text-center text-muted">
        <div>
          <p className="text-lg">Select or load a company to begin.</p>
          <p className="mt-1 text-sm">
            Use the search on the left. The seeded example is <span className="font-mono text-accent">VALX</span>.
          </p>
        </div>
      </div>
    );
  }

  if (loading && !summary) return <Spinner label={`Loading ${ticker}…`} />;
  if (error) return <ErrorNote message={error} />;
  if (!summary) return null;

  return (
    <div className="space-y-4">
      <Panel>
        <CompanyHeader summary={summary} />
      </Panel>

      <Panel title="Financial inputs (SEC-normalized)">
        <FinancialTable metrics={metrics} />
      </Panel>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Valuation — DCF">
          <ValuationPanel ticker={ticker} />
        </Panel>
        <Panel title="Signal — transparent scoring">
          <SignalPanel ticker={ticker} onRun={() => setSignalNonce((n) => n + 1)} />
        </Panel>
      </div>

      <Panel title="Clinical / FDA catalysts">
        <CatalystTimeline ticker={ticker} />
      </Panel>

      {/* signalNonce forces a lightweight refresh hook point for future widgets */}
      <span className="hidden">{signalNonce}</span>
    </div>
  );
}
