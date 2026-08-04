// Shared API response types (mirrors the backend serializers).

export interface Company {
  id: number;
  ticker: string;
  cik: string | null;
  name: string;
  sector: string | null;
  industry: string | null;
  exchange: string | null;
  currency: string;
  is_example: boolean;
  source: string;
  updated_at: string | null;
  counts?: {
    filings: number;
    metrics: number;
    catalysts: number;
    signal_runs: number;
  };
}

export interface Metric {
  id: number;
  concept: string;
  value: number | null;
  unit: string;
  fiscal_year: number | null;
  fiscal_period: string | null;
  period_start: string | null;
  period_end: string | null;
  source: string;
  provenance: {
    xbrl_concept: string | null;
    taxonomy: string | null;
    accession_number: string | null;
    form: string | null;
  };
  quality: {
    status: string;
    confidence: number;
    note: string | null;
  };
}

export interface CompanySummary {
  company: Company;
  latest_fiscal_year: number | null;
  key_metrics: Record<string, Metric>;
  data_quality_warnings: string[];
}

export interface Filing {
  id: number;
  accession_number: string;
  form: string;
  fiscal_year: number | null;
  fiscal_period: string | null;
  period_end: string | null;
  filed_date: string | null;
  source: string;
}

export interface Catalyst {
  id: number;
  company_id: number;
  drug_program: string;
  indication: string | null;
  event_type: string;
  trial_phase: string | null;
  expected_date: string | null;
  actual_date: string | null;
  outcome: string;
  source_url: string | null;
  notes: string | null;
  source: string;
  updated_at: string | null;
}

export interface DcfProjection {
  year: number;
  revenue: number;
  ebit: number;
  nopat: number;
  capex: number;
  delta_nwc: number;
  fcff: number;
  discount_factor: number;
  pv_fcff: number;
}

export interface DcfScenario {
  scenario: string;
  assumptions: Record<string, number>;
  projections: DcfProjection[];
  pv_fcff_sum: number;
  terminal_value: number;
  pv_terminal_value: number;
  enterprise_value: number;
  equity_value: number;
  implied_share_price: number;
  warnings: string[];
}

export interface ValuationResponse {
  company: { id: number; ticker: string; name: string };
  inputs: {
    base_revenue: number;
    net_debt: number;
    shares_outstanding: number;
    sources: Record<string, string>;
    fiscal_year: number | null;
    warnings: string[];
  };
  assumptions: Record<string, number>;
  scenarios: Record<"base" | "bull" | "bear", DcfScenario>;
  sensitivity: {
    wacc_values: number[];
    terminal_growth_values: number[];
    implied_share_price: (number | null)[][];
  } | null;
  disclaimer: string;
}

export interface SignalComponent {
  name: string;
  input_value: unknown;
  weight: number;
  contribution: number;
  explanation: string;
}

export interface SignalResponse {
  company: { id: number; ticker: string };
  signal: "long" | "short" | "watchlist";
  score: number;
  confidence: number;
  components: SignalComponent[];
  rationale: string;
  warnings: string[];
  inputs_used: Record<string, unknown>;
  auto_derived: Record<string, string>;
  persisted_run_id: number | null;
  disclaimer: string;
}

export interface SignalRun {
  id: number;
  company_id: number;
  signal: string;
  score: number;
  confidence: number;
  as_of_date: string | null;
  engine_version: string;
  inputs_snapshot: Record<string, unknown> | null;
  rationale: { text: string; components: SignalComponent[]; warnings: string[] } | null;
  created_at: string | null;
}

export interface BacktestResponse {
  company_id: number;
  ticker: string;
  methodology: string;
  signals_total: number;
  evaluated: number;
  directional_agreement_rate: number | null;
  note: string;
  details: Array<{
    signal_run_id: number;
    signal: string;
    as_of_date: string;
    next_resolved_outcome: string;
    resolved_on: string;
    agreement: boolean;
  }>;
}

export interface Meta {
  provider: string;
  disclaimer: string;
  available_mock_tickers: string[];
  cache_ttl_company_facts_s: number;
}
