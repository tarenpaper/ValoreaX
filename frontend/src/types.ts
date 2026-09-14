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
  /** Stage-aware biotech figures; null when the company has no stored metrics. */
  biotech_profile: BiotechProfile | null;
  data_quality_warnings: string[];
}

export type BiotechStage = "pre_revenue" | "cash_burning" | "cash_generative";

/** A headline figure computed from stored SEC metrics (see biotech_profile.py). */
export interface BiotechFigure {
  value: number | null;
  unit: "USD" | "ratio" | "quarters";
  status: "reported" | "derived" | "missing" | "not_meaningful" | "inconsistent" | "estimated";
  source: string;
  confidence: number;
  note: string | null;
  inputs: string[];
}

export interface BiotechProfile {
  fiscal_year: number | null;
  stage: BiotechStage;
  stage_label: string;
  stage_reason: string;
  headline: string[];
  figures: Record<string, BiotechFigure>;
  thresholds: { pre_revenue_spend_ratio: number };
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
  external_id: string | null;
  updated_at: string | null;
}

export interface CatalystIngestResponse {
  company_id: number;
  ticker: string;
  ingestion: {
    provider: string;
    fetched: number;
    added: number;
    updated: number;
    skipped: number;
    was_cached: boolean;
    warnings: string[];
  };
  catalysts: Catalyst[];
  disclaimer: string;
}

export interface AnalystConsensus {
  distribution: { strong_buy: number; buy: number; hold: number; sell: number; strong_sell: number };
  analyst_count: number;
  consensus_label: string | null;
  targets: { high: number | null; low: number | null; consensus: number | null; median: number | null };
  current_price: number | null;
  implied_upside: number | null;
  as_of_date: string | null;
  source: string;
}

export interface AnalystRating {
  institution: string;
  grade: string | null;
  action: string | null;
  price_target: number | null;
  rating_date: string | null;
  source: string;
}

export interface AnalystResponse {
  company_id: number;
  ticker: string;
  consensus: AnalystConsensus | null;
  ratings: AnalystRating[];
  disclaimer: string;
}

export interface AnalystIngestResponse {
  company_id: number;
  ticker: string;
  ingestion: {
    provider: string;
    analyst_count: number;
    rating_rows: number;
    consensus_label: string | null;
    target_consensus: number | null;
    implied_upside: number | null;
    was_cached: boolean;
    warnings: string[];
  };
  consensus: AnalystConsensus | null;
  ratings: AnalystRating[];
  disclaimer: string;
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

export interface ClinicalStatus {
  state: "upcoming" | "overdue" | "recent" | "none";
  label: string;
  catalyst_id: number | null;
}

export interface WatchlistRow {
  id: number;
  ticker: string;
  name: string;
  source: string;
  is_example: boolean;
  price: number | null;
  change_pct: number | null;
  change_7d: number | null;
  series: number[];
  clinical_status: ClinicalStatus;
  signal: string | null;
}

export interface WatchlistResponse {
  count: number;
  as_of: string;
  companies: WatchlistRow[];
  disclaimer: string;
}

export interface NewsSentiment {
  label: string;
  score: number;
  method: string;
}

export interface NewsArticle {
  id: number;
  external_id: string;
  headline: string;
  summary: string | null;
  source: string | null;
  url: string | null;
  published_at: string | null;
  related: string | null;
  sentiment: NewsSentiment;
  impact: string;
  tags: string[];
  provider: string;
  clinical_relevance: number;
  is_clinical: boolean;
}

export interface CatalystMatrixRow {
  asset: string;
  indication: string | null;
  news_volume: number;
  sentiment_score: number;
  confidence: string;
  trial_count: number;
  match_terms: string[];
}

export interface TrendingTopic {
  topic: string;
  count: number;
}

export interface SectorSentiment {
  sector: string;
  avg_score: number;
  count: number;
}

export interface NewsMarker {
  date: string;
  label: string;
  kind: string;
  sentiment: string | null;
  relevance: number | null;
}

export interface NewsView {
  company: { id: number; ticker: string; name: string; sector: string | null };
  as_of: string;
  summary: { total: number; bullish: number; bearish: number; neutral: number; clinical: number };
  articles: NewsArticle[];
  catalyst_matrix: CatalystMatrixRow[];
  trending_topics: TrendingTopic[];
  sector_sentiment: SectorSentiment[];
  price_series: Array<{ date: string; close: number }>;
  markers: NewsMarker[];
  disclaimer: string;
}

export interface NewsIngestResponse extends NewsView {
  company_id: number;
  ticker: string;
  ingestion: {
    provider: string;
    fetched: number;
    added: number;
    skipped: number;
    was_cached: boolean;
    warnings: string[];
  };
}

export interface Meta {
  sources?: Record<string, { provider: string; state: "configured" | "needs_setup" | "sample" | "manual" | "unknown"; missing_setting: string | null }>;
  provider: string;
  market_provider: string;
  catalyst_provider: string;
  analyst_provider: string;
  news_provider: string;
  disclaimer: string;
  available_mock_tickers: string[];
  cache_ttl_company_facts_s: number;
}

export interface InvestmentBacktest {
  ticker: string; benchmark: string; source: string; currency: string; adjustment: string;
  requested_start: string; requested_end: string; entry_date: string; exit_date: string;
  investment: number; final_value: number; profit_loss: number; total_return: number;
  benchmark_return: number; benchmark_final_value: number; excess_return: number;
  annualized_return: number | null; max_drawdown: number; trading_sessions: number;
  entry_close: number; exit_close: number;
  curve: Array<{ date: string; close: number; value: number; benchmark_value: number;
    return_pct: number; drawdown: number; outlook: string }>;
  entry_outlook: HistoricalOutlook; exit_outlook: HistoricalOutlook;
  warnings: string[]; methodology: string; outlook_methodology: string;
  retrieval: Array<{ symbol: string; cached: boolean; fetched_at: string }>;
  /** Present only when the request set explain: true. */
  explanation?: BacktestExplanation;
}

/** Retrospective Plutus commentary on a finished simulation — never a forecast. */
export type BacktestExplanation =
  | { status: "needs_setup" | "error"; message: string }
  | {
      status: "ready"; model: string; generated_at: string; cached: boolean;
      summary: string;
      observations: Array<{ text: string; evidence_ids: string[] }>;
      cautions: Array<{ text: string; evidence_ids: string[] }>;
      tensions: Array<{ text: string; evidence_ids: string[] }>;
      /**
       * Events explaining the detected inflection points. `sourced` entries cite a
       * supplied news record; unsourced ones are model recollection and must always be
       * rendered as unverified. `confidence` grades the causal link, not the event.
       */
      context: Array<{
        text: string; approximate_date: string; confidence: "high" | "medium" | "low";
        evidence_ids: string[]; sourced: boolean;
      }>;
      limitations: string[];
      evidence: Array<{ id: string; label: string; data: unknown }>;
    };
export interface HistoricalOutlook {
  as_of: string | null; label: string; sma20: number | null; sma60: number | null;
  trailing_return: number | null;
}

export type ResearchResponse = { status: "needs_setup"; message: string } | {
  status: "ready"; ticker: string; model: string; generated_at: string; cached: boolean;
  summary: string; outlook: "positive" | "mixed" | "negative" | "insufficient_data";
  drivers: Array<{ text: string; evidence_ids: string[] }>;
  risks: Array<{ text: string; evidence_ids: string[] }>;
  /** Where the deterministic DCF/signal outputs conflict with the other evidence. */
  tensions: Array<{ text: string; evidence_ids: string[] }>;
  limitations: string[];
  evidence: Array<{ id: string; label: string; data: unknown }>;
};

export interface ClinicalMLTrial {
  nct_id: string;
  title: string | null;
  interventions: string[];
  conditions: string[];
  phase: string;
  registry_status: string | null;
  source_url: string;
  snapshot_at: string;
  status: "research_estimate" | "insufficient_evidence";
  probability: number | null;
  reasons: string[];
  drivers: { feature: string; log_odds_contribution: number }[];
}

export interface ClinicalMLView {
  ticker: string;
  target: string;
  model_status: "not_configured" | "research_candidate" | "evaluation_failed";
  model_error: string | null;
  model_id: string | null;
  retrieved_at: string | null;
  truncated: boolean;
  ingestion_enabled: boolean;
  trials: ClinicalMLTrial[];
  limitations: string[];
  evaluation: null | {
    model: { n: number; brier: number; roc_auc: number | null };
    phase_baseline: { brier: number };
  };
}
