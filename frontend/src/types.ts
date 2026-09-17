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

/** One projected year of a single drug's mini-company model. */
export interface AssetYear {
  year: number;
  revenue: number;
  gross_profit: number;
  commercial_cost: number;
  development_cost: number;
  pretax: number;
  tax: number;
  cash_flow: number;
  risked_cash_flow: number;
  discount_factor: number;
  present_value: number;
}

/** Where a modelled input came from, so nothing derived can pass as reported. */
export type Provenance = "sec" | "sec_quoted" | "derived" | "benchmark" | "override";

export interface AssetProvenance {
  id: number;
  key: string;
  indication: string | null;
  phase: string | null;
  origin: string;
  included: boolean;
  xbrl_member: string | null;
  overrides: string[];
  values: Record<string, unknown>;
  extracted: Record<string, unknown>;
  sources: Record<string, Provenance>;
  loe_note?: string;
}

export interface ValuedAsset {
  name: string;
  kind: "marketed" | "pipeline" | "royalty";
  probability: number;
  rnpv: number | null;
  unrisked_npv: number | null;
  peak_revenue: number | null;
  loe_year: number | null;
  years: AssetYear[];
  unvalued_reason: string | null;
  provenance?: AssetProvenance;
}

export interface ValuationResponse {
  current_price: number | null;
  price_as_of: string | null;
  price_source: string | null;
  price_to_sotp: number | null;
  company: { id: number; ticker: string; name: string };
  discount_rate: number;
  start_year: number;
  horizon_years: number;
  assets: ValuedAsset[];
  unvalued: ValuedAsset[];
  excluded: string[];
  asset_value: number | null;
  /** Programmes the filing gives no patient population for, on a weaker analog. */
  continuing_value: {
    value: number;
    programmes: Array<{
      name: string;
      phase: string | null;
      probability: number;
      rnpv: number;
      assumed_peak_sales: number;
    }>;
    abandoned?: number;
    analog_peak_sales?: number | null;
    basis?: string;
    haircut?: number;
    note?: string;
  };
  overhead_present_value: number;
  overhead_per_year: number;
  net_cash: number;
  equity_value: number | null;
  value_per_share: number | null;
  shares_outstanding: number | null;
  note: string | null;
  method: string;
  economics: {
    sources: Record<string, Provenance>;
    gross_margin: number;
    commercial_cost_rate: number;
    tax_rate: number;
    development_cost_per_year: number;
    revenue: number;
    sga: number | null;
    research_development: number;
  };
  sensitivity: {
    discount_rates: number[];
    revenue_multipliers: number[];
    value_per_share: (number | null)[][];
  } | null;
}

/** A drug as stored: what the filing said, plus the user's edits kept separately. */
export interface DrugAsset {
  id: number;
  key: string;
  name: string;
  kind: "marketed" | "pipeline" | "royalty";
  origin: string;
  indication: string | null;
  phase: string | null;
  modality: string | null;
  included: boolean;
  xbrl_member: string | null;
  extracted: Record<string, unknown>;
  overrides: Record<string, number | string>;
}

export interface ProductRevenueLine {
  member: string;
  label: string;
  fiscal_year: number;
  value: number;
  us_value: number | null;
  classification: string;
  reason: string | null;
  geography_basis: string | null;
  accession_number: string | null;
}

export interface DrugsResponse {
  company_id: number;
  ticker: string;
  drugs: DrugAsset[];
  product_revenues: ProductRevenueLine[];
}

export interface DrugSyncResponse {
  company_id: number;
  ticker: string;
  accession_number: string | null;
  skipped: boolean;
  product_lines: number;
  drugs: number;
  unvalued: number;
  warnings: string[];
}

export interface SignalComponent {
  name: string;
  input_value: unknown;
  weight: number;
  contribution: number;
  explanation: string;
  /** Which reference the valuation was read against: peer_median, own_range, manual_upside. */
  basis?: string | null;
}

/** A factor the engine could not compute, and why. A gap is not a neutral reading. */
export interface SkippedComponent {
  name: string;
  reason: string;
}

export interface SignalResponse {
  company: { id: number; ticker: string };
  signal: "long" | "short" | "watchlist";
  score: number;
  confidence: number;
  components: SignalComponent[];
  skipped: SkippedComponent[];
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
  watched: boolean;
  price: number | null;
  change_pct: number | null;
  change_7d: number | null;
  series: number[];
  clinical_status: ClinicalStatus;
  signal: string | null;
}

export interface WatchlistResponse {
  count: number;
  /** Cap on watched companies — each needs its own daily price request. */
  limit: number;
  remaining: number;
  as_of: string;
  companies: WatchlistRow[];
  disclaimer: string;
}

export interface BasketMember {
  ticker: string;
  name: string | null;
  company_id: number | null;
  watched: boolean;
  /** False when the basket names a company the account no longer holds. */
  available: boolean;
}

/** A named group whose name is an anagram of its members' initials — MANGO, FAANG. */
export interface Basket {
  id: number;
  name: string;
  members: BasketMember[];
  size: number;
  /** Every member is currently watched, i.e. this basket is the live watchlist. */
  active: boolean;
}

export interface BasketsResponse {
  count: number;
  limit: number;
  baskets: Basket[];
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
  benchmarks: Array<{ symbol: string; final_value: number; profit_loss: number;
    total_return: number; annualized_return: number | null; max_drawdown: number; excess_return: number }>;

  ticker: string; benchmark: string; source: string; currency: string; adjustment: string;
  requested_start: string; requested_end: string; entry_date: string; exit_date: string;
  investment: number; final_value: number; profit_loss: number; total_return: number;
  benchmark_return: number; benchmark_final_value: number; excess_return: number;
  annualized_return: number | null; max_drawdown: number; trading_sessions: number;
  entry_close: number; exit_close: number;
  curve: Array<{ date: string; close: number; value: number; benchmark_value: number;
    return_pct: number; drawdown: number; outlook: string;
    comparisons: Record<string, { value: number; return_pct: number; drawdown: number }> }>;
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
  /** Where the deterministic valuation/signal outputs conflict with the other evidence. */
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
