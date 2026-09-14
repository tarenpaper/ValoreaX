// Thin typed API client. All calls go through `request`, which normalizes the
// backend's consistent error envelope into thrown ApiError instances.
import { supabase } from "../auth/supabase";
import type {
  ClinicalMLView,
  ResearchResponse,
  AnalystIngestResponse,
  AnalystResponse,
  BacktestResponse,
  Catalyst,
  CatalystIngestResponse,
  Company,
  CompanySummary,
  Filing,
  InvestmentBacktest,
  Meta,
  Metric,
  NewsIngestResponse,
  NewsView,
  SignalResponse,
  SignalRun,
  ValuationResponse,
  WatchlistResponse,
} from "../types";

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:5001/api/v1";

export class ApiError extends Error {
  code: string;
  status: number;
  details: unknown;
  constructor(message: string, code: string, status: number, details: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  if (!supabase) throw new ApiError("Authentication is not configured.", "auth_unavailable", 503, null);
  const { data: { session }, error } = await supabase.auth.getSession();
  if (error || !session) throw new ApiError("Please sign in again.", "unauthorized", 401, null);
  const headers = new Headers(options?.headers);
  headers.set("Content-Type", "application/json");
  headers.set("Authorization", `Bearer ${session.access_token}`);
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  const text = await resp.text();
  const body = text ? JSON.parse(text) : null;
  if (!resp.ok) {
    if (resp.status === 401) {
      // A late response from a previous account must not sign out a new session.
      const { data } = await supabase.auth.getSession();
      if (data.session?.access_token === session.access_token) {
        await supabase.auth.signOut({ scope: "local" });
      }
    }
    const err = body?.error ?? {};
    throw new ApiError(
      err.message ?? `Request failed (${resp.status})`,
      err.code ?? "error",
      resp.status,
      err.details ?? null,
    );
  }
  return body as T;
}

const navigationRequests = new Map<string, Promise<{ warnings: string[] }>>();

export const api = {
  clinicalML: (ticker: string) => request<ClinicalMLView>(`/companies/${ticker}/clinical-ml`),
  ingestClinicalML: (ticker: string) => request<ClinicalMLView>(`/companies/${ticker}/clinical-ml/ingest`, { method: "POST" }),
  research: (ticker: string, question = "", assumptions?: Record<string, number> | null, scope: "company" | "clinical" = "company") => request<ResearchResponse>(`/companies/${ticker}/research`, { method: "POST", body: JSON.stringify({ question, assumptions, scope }) }),
  refreshNavigation: async (view: string, ticker: string | null) => {
    const { data } = await supabase!.auth.getSession();
    const key = `${data.session?.user.id}:${view}:${ticker}`;
    const existing = navigationRequests.get(key);
    if (existing) return existing;
    const pending = request<{ warnings: string[] }>("/navigation/refresh", {
      method: "POST", body: JSON.stringify({ view, ticker }),
    }).finally(() => navigationRequests.delete(key));
    navigationRequests.set(key, pending);
    return pending;
  },
  meta: () => request<Meta>("/meta"),

  listCompanies: (query = "") =>
    request<{ companies: Company[]; provider: string; available_mock_tickers: string[] }>(
      `/companies${query ? `?query=${encodeURIComponent(query)}` : ""}`,
    ),

  ingestCompany: (ticker: string) =>
    request<{ company: Company; ingestion: { warnings: string[]; metric_count: number } }>(
      "/companies",
      { method: "POST", body: JSON.stringify({ ticker }) },
    ),

  summary: (ticker: string) => request<CompanySummary>(`/companies/${ticker}/summary`),
  refreshCompany: (ticker: string) => request(`/companies/${ticker}/refresh`, { method: "POST" }),
  metrics: (ticker: string) =>
    request<{ metrics: Metric[]; count: number }>(`/companies/${ticker}/metrics`),
  filings: (ticker: string) =>
    request<{ filings: Filing[]; count: number }>(`/companies/${ticker}/filings`),

  valuation: (ticker: string, assumptions: Record<string, number>) =>
    request<ValuationResponse>(`/companies/${ticker}/valuation`, {
      method: "POST",
      body: JSON.stringify({ assumptions }),
    }),

  listCatalysts: (ticker: string) =>
    request<{ catalysts: Catalyst[]; count: number }>(`/companies/${ticker}/catalysts`),
  createCatalyst: (ticker: string, payload: Partial<Catalyst>) =>
    request<Catalyst>(`/companies/${ticker}/catalysts`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateCatalyst: (id: number, payload: Partial<Catalyst>) =>
    request<Catalyst>(`/catalysts/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteCatalyst: (id: number) =>
    request<{ deleted: boolean }>(`/catalysts/${id}`, { method: "DELETE" }),
  ingestCatalysts: (ticker: string) =>
    request<CatalystIngestResponse>(`/companies/${ticker}/catalysts/ingest`, { method: "POST" }),

  getAnalysts: (ticker: string) =>
    request<AnalystResponse>(`/companies/${ticker}/analysts`),
  ingestAnalysts: (ticker: string) =>
    request<AnalystIngestResponse>(`/companies/${ticker}/analysts/ingest`, { method: "POST" }),

  runSignal: (ticker: string, payload: Record<string, unknown>) =>
    request<SignalResponse>(`/companies/${ticker}/signals`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listSignals: (ticker: string) =>
    request<{ signal_runs: SignalRun[]; count: number }>(`/companies/${ticker}/signals`),
  backtest: (ticker: string) =>
    request<BacktestResponse>(`/companies/${ticker}/signals/backtest`),
  simulateInvestment: (ticker: string, payload: { start_date: string; end_date: string; investment: number; explain?: boolean; question?: string }) =>
    request<InvestmentBacktest>(`/companies/${ticker}/backtest`, { method: "POST", body: JSON.stringify(payload) }),

  syncPrices: (ticker: string) =>
    request<{ synced: number }>(`/companies/${ticker}/prices/sync`, { method: "POST" }),

  watchlist: () => request<WatchlistResponse>("/watchlist"),

  news: (ticker: string) => request<NewsView>(`/companies/${ticker}/news`),
  ingestNews: (ticker: string) =>
    request<NewsIngestResponse>(`/companies/${ticker}/news/ingest`, { method: "POST" }),
};

export { BASE_URL };
