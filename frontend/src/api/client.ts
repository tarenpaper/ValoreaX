// Thin typed API client. All calls go through `request`, which normalizes the
// backend's consistent error envelope into thrown ApiError instances.
import type {
  BacktestResponse,
  Catalyst,
  Company,
  CompanySummary,
  Filing,
  Meta,
  Metric,
  SignalResponse,
  SignalRun,
  ValuationResponse,
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
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await resp.text();
  const body = text ? JSON.parse(text) : null;
  if (!resp.ok) {
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

export const api = {
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

  runSignal: (ticker: string, payload: Record<string, unknown>) =>
    request<SignalResponse>(`/companies/${ticker}/signals`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listSignals: (ticker: string) =>
    request<{ signal_runs: SignalRun[]; count: number }>(`/companies/${ticker}/signals`),
  backtest: (ticker: string) =>
    request<BacktestResponse>(`/companies/${ticker}/signals/backtest`),

  syncPrices: (ticker: string) =>
    request<{ synced: number }>(`/companies/${ticker}/prices/sync`, { method: "POST" }),
};

export { BASE_URL };
