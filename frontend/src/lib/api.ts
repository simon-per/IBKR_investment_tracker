/**
 * API Client for IBKR Portfolio Analyzer Backend
 */

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface AppSettings {
  base_currency: string;
  supported_currencies: string[];
}

export interface PortfolioValuePoint {
  date: string;
  // NOTE: *_eur fields carry values in the selected base_currency (see base_currency).
  cost_basis_eur: number;
  market_value_eur: number;
  gain_loss_eur: number;
  gain_loss_percent: number;
  base_currency?: string;
}

export interface PortfolioSummary {
  // NOTE: *_eur fields carry values in the selected base_currency (see base_currency).
  total_cost_basis_eur: number;
  total_market_value_eur: number;
  total_gain_loss_eur: number;
  total_gain_loss_percent: number;
  num_positions: number;
  date?: string;
  base_currency?: string;
  total_realized_gain_loss_eur: number;
  total_realized_proceeds_eur: number;
  total_realized_cost_basis_eur: number;
  num_closed_positions: number;
}

export interface TaxLotInfo {
  open_date: string;
  quantity: number;
  cost_basis: number;
  cost_basis_eur: number;
}

export interface AnalystRating {
  strong_buy: number;
  buy: number;
  hold: number;
  sell: number;
  strong_sell: number;
  total_ratings: number;
  consensus: string;
  last_updated: string;
}

export interface Position {
  security_id: number;
  symbol: string;
  description: string;
  isin: string;
  currency: string;
  exchange: string | null;
  quantity: number;
  cost_basis_eur: number;
  market_value_eur: number;
  market_price: number | null;
  gain_loss_eur: number;
  gain_loss_percent: number;
  taxlots: TaxLotInfo[];
  analyst_rating: AnalystRating | null;
}

export interface AnnualizedReturnResponse {
  method: string;
  annualized_return_pct: number | null;
  start_date: string;
  end_date: string;
  num_cash_flows: number;
}

export interface SchedulerJob {
  id: string;
  name: string;
  next_run_time: string | null;
  trigger: string;
}

export interface SchedulerStatus {
  status: string;
  jobs: SchedulerJob[];
  last_sync: {
    type: string;
    timestamp: string;
    status: string;
    /** Populated on failures — e.g. the IBKR Code=1025 lockout explanation. */
    message?: string | null;
    /** Flex XML schema drift the sanitizer worked around, skipped currencies, etc. */
    warnings?: string[] | null;
    details?: Record<string, unknown> | null;
  } | null;
  message?: string;
}

export interface SyncRun {
  type: string;
  status: string;
  timestamp: string | null;
  message?: string | null;
  warnings?: string[] | null;
  details?: Record<string, unknown> | null;
}

export interface SyncHistory {
  count: number;
  runs: SyncRun[];
}

export interface BenchmarkInfo {
  key: string;
  name: string;
  ticker: string;
  currency: string;
}

export interface BenchmarkValuePoint {
  date: string;
  benchmark_value_eur: number;
  cost_basis_eur: number;
  gain_loss_eur: number;
  gain_loss_percent: number;
}

export interface BenchmarkResponse {
  benchmark_name: string;
  benchmark_ticker: string;
  data: BenchmarkValuePoint[];
}

export interface SecurityAttribution {
  security_id: number;
  symbol: string;
  description: string;
  start_market_value_eur: number;
  end_market_value_eur: number;
  new_investment_eur: number;
  value_change_eur: number;
  pnl_contribution_eur: number;
  contribution_percent: number;
  weight_percent: number;
}

export interface PerformanceAttributionResponse {
  start_date: string;
  end_date: string;
  total_pnl_eur: number;
  attributions: SecurityAttribution[];
}

export interface AllocationPosition {
  symbol: string;
  description: string;
  weight: number;
  market_value_eur: number;
  is_etf_contribution: boolean;
}

export interface AllocationCategory {
  percentage: number;
  market_value_eur: number;
  positions: AllocationPosition[];
}

export interface PortfolioAllocationResponse {
  sector_allocation: Record<string, AllocationCategory>;
  geographic_allocation: Record<string, AllocationCategory>;
  asset_type_allocation: Record<string, AllocationCategory>;
  total_market_value_eur: number;
}

export interface SyncResponse {
  message: string;
  securities_synced: number;
  taxlots_synced: number;
  warnings?: string[];
}

export interface FundamentalMetrics {
  security_id: number;
  symbol: string;
  description: string;
  exchange: string | null;
  currency: string;
  quote_type: string | null;
  trailing_pe: number | null;
  forward_pe: number | null;
  peg_ratio: number | null;
  price_to_sales: number | null;
  price_to_book: number | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  fwd_revenue_growth: number | null;
  fwd_eps_growth: number | null;
  profit_margins: number | null;
  gross_margins: number | null;
  operating_margins: number | null;
  market_cap: number | null;
  number_of_analysts: number | null;
  target_mean_price: number | null;
  target_high_price: number | null;
  target_low_price: number | null;
  data_currency: string | null;
  last_updated: string | null;
}

export interface EarningsCalendarItem {
  security_id: number;
  symbol: string;
  description: string;
  earnings_date: string;
  eps_estimate: number | null;
}

export interface EarningsHistoryItem {
  security_id: number;
  symbol: string;
  description: string;
  earnings_date: string;
  eps_estimate: number | null;
  reported_eps: number | null;
  surprise_percent: number | null;
  beat_or_miss: string | null;
}

export interface FundamentalsStatus {
  total_securities: number;
  securities_with_data: number;
  securities_without_data: number;
  stale_metrics: number;
  total_earnings_events: number;
  oldest_update: string | null;
  newest_update: string | null;
}

export interface FundamentalsSyncResponse {
  status: string;
  securities_processed: number;
  metrics_updated: number;
  earnings_updated: number;
  errors: number;
  message: string;
}

export interface WatchlistItem {
  id: number;
  yahoo_ticker: string;
  symbol: string | null;
  company_name: string | null;
  notes: string | null;
  target_price: number | null;
  current_price: number | null;
  currency: string | null;
  trailing_pe: number | null;
  forward_pe: number | null;
  peg_ratio: number | null;
  ev_to_ebitda: number | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  fwd_revenue_growth: number | null;
  fwd_eps_growth: number | null;
  profit_margins: number | null;
  market_cap: number | null;
  analyst_target: number | null;
  analyst_rating: string | null;
  analyst_count: number | null;
  week52_high: number | null;
  week52_low: number | null;
  pct_from_52w_high: number | null;
  ma200: number | null;
  ma50: number | null;
  pct_from_ma200: number | null;
  rsi14: number | null;
  buy_score: number | null;
  data_currency: string | null;
  last_synced: string | null;
  created_at: string | null;
}

export interface DividendMonthlyItem {
  month: string;
  amount_eur: number;
}

export interface DividendSummaryResponse {
  monthly: DividendMonthlyItem[];
  ytd_eur: number;
  total_eur: number;
  last_updated: string | null;
  sync_in_progress: boolean;
}

export interface TaxDividendRow {
  symbol: string | null;
  description: string | null;
  isin: string | null;
  pay_date: string;
  gross: number;
  withholding: number;
  net: number;
}

export interface TaxCountryRow {
  /** ISIN prefix, e.g. "US", "CH", "DE". "??" when the ISIN is unknown. */
  country: string;
  positions: number;
  gross: number;
  withholding: number;
  net: number;
}

export interface TaxRealizedRow {
  symbol: string | null;
  trade_date: string;
  quantity: number | null;
  proceeds: number;
  cost_basis: number;
  gain_loss: number;
}

export interface TaxHoldingRow {
  symbol: string | null;
  quantity: number | null;
  market_value: number;
  cost_basis: number;
}

export interface TaxReport {
  year: number;
  base_currency: string;
  dividend_source: 'ibkr' | 'yfinance_estimate';
  dividend_income: TaxDividendRow[];
  /** Withholding grouped by source country — DA-1 is filed per country. */
  dividend_by_country: TaxCountryRow[];
  dividend_country_note: string;
  dividend_totals: { gross: number; withholding: number; net: number };
  realized_gains: TaxRealizedRow[];
  realized_source: 'trades' | 'closed_lot_estimate';
  /** Date the holdings snapshot is valued at — 31 Dec for past years, today otherwise. */
  holdings_as_of: string;
  realized_totals: { proceeds: number; cost_basis: number; gain_loss: number };
  holdings_snapshot: TaxHoldingRow[];
  holdings_snapshot_total: number;
  holdings_snapshot_note: string;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `HTTP ${response.status}: ${response.statusText}`);
      }

      return response.json();
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('Network request failed');
    }
  }

  // Settings endpoints
  async getSettings(): Promise<AppSettings> {
    return this.request<AppSettings>('/api/settings');
  }

  async updateBaseCurrency(baseCurrency: string): Promise<AppSettings> {
    return this.request<AppSettings>('/api/settings/base-currency', {
      method: 'PUT',
      body: JSON.stringify({ base_currency: baseCurrency }),
    });
  }

  // Portfolio endpoints
  async getPortfolioValueOverTime(
    startDate?: string,
    endDate?: string
  ): Promise<PortfolioValuePoint[]> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request<PortfolioValuePoint[]>(`/api/portfolio/value-over-time${query}`);
  }

  async getPortfolioSummary(): Promise<PortfolioSummary> {
    return this.request<PortfolioSummary>('/api/portfolio/summary');
  }

  async getAnnualizedReturn(startDate: string, endDate: string): Promise<AnnualizedReturnResponse> {
    return this.request<AnnualizedReturnResponse>(
      `/api/portfolio/annualized-return?start_date=${startDate}&end_date=${endDate}`
    );
  }

  async getPositions(): Promise<Position[]> {
    return this.request<Position[]>('/api/portfolio/positions');
  }

  async getPerformanceAttribution(startDate: string, endDate: string): Promise<PerformanceAttributionResponse> {
    return this.request<PerformanceAttributionResponse>(
      `/api/portfolio/attribution?start_date=${startDate}&end_date=${endDate}`
    );
  }

  async getAvailableBenchmarks(): Promise<BenchmarkInfo[]> {
    return this.request<BenchmarkInfo[]>('/api/portfolio/benchmarks');
  }

  async getBenchmarkComparison(
    startDate: string, endDate: string, benchmark: string = 'sp500'
  ): Promise<BenchmarkResponse> {
    return this.request<BenchmarkResponse>(
      `/api/portfolio/benchmark?start_date=${startDate}&end_date=${endDate}&benchmark=${benchmark}`
    );
  }

  // Sync endpoint
  async syncIBKRData(): Promise<SyncResponse> {
    return this.request<SyncResponse>('/api/sync/ibkr', {
      method: 'POST',
    });
  }

  // Analyst ratings endpoints
  async syncAnalystRatings(): Promise<{ status: string; securities_processed: number; ratings_updated: number; errors: number; message: string }> {
    return this.request('/api/analyst-ratings/sync', {
      method: 'POST',
    });
  }

  async getAnalystRatingsStatus(): Promise<{ total_ratings: number; stale_ratings: number; fresh_ratings: number; oldest_update: string | null; newest_update: string | null }> {
    return this.request('/api/analyst-ratings/status');
  }

  // Allocation endpoints
  async syncAllocationData(forceRefresh: boolean = false): Promise<{ securities_processed: number; securities_updated: number; errors: number; message: string }> {
    return this.request(`/api/allocation/sync?force_refresh=${forceRefresh}`, {
      method: 'POST',
    });
  }

  async getPortfolioAllocation(): Promise<PortfolioAllocationResponse> {
    return this.request('/api/allocation/portfolio');
  }

  async getAllocationStatus(): Promise<{
    total_securities: number;
    securities_with_data: number;
    securities_without_data: number;
    stale_securities: number;
    oldest_update: string | null;
    newest_update: string | null;
  }> {
    return this.request('/api/allocation/status');
  }

  // Scheduler endpoints
  async getSyncHistory(limit = 20): Promise<SyncHistory> {
    return this.request<SyncHistory>(`/api/scheduler/history?limit=${limit}`);
  }

  async getSchedulerStatus(): Promise<SchedulerStatus> {
    return this.request<SchedulerStatus>('/api/scheduler/status');
  }

  // Fundamentals endpoints
  async syncFundamentals(forceRefresh: boolean = false): Promise<FundamentalsSyncResponse> {
    return this.request(`/api/fundamentals/sync?force_refresh=${forceRefresh}`, {
      method: 'POST',
    });
  }

  async getPortfolioFundamentals(): Promise<FundamentalMetrics[]> {
    return this.request('/api/fundamentals/portfolio');
  }

  async getUpcomingEarnings(daysAhead: number = 90): Promise<EarningsCalendarItem[]> {
    return this.request(`/api/fundamentals/earnings/upcoming?days_ahead=${daysAhead}`);
  }

  async getEarningsHistory(daysBack: number = 365): Promise<EarningsHistoryItem[]> {
    return this.request(`/api/fundamentals/earnings/history?days_back=${daysBack}`);
  }

  async getFundamentalsStatus(): Promise<FundamentalsStatus> {
    return this.request('/api/fundamentals/status');
  }

  // Watchlist endpoints
  async getWatchlist(): Promise<WatchlistItem[]> {
    return this.request('/api/watchlist');
  }

  async addToWatchlist(yahooTicker: string, notes?: string, targetPrice?: number): Promise<WatchlistItem> {
    return this.request('/api/watchlist', {
      method: 'POST',
      body: JSON.stringify({
        yahoo_ticker: yahooTicker,
        notes: notes || null,
        target_price: targetPrice || null,
      }),
    });
  }

  async updateWatchlistItem(id: number, notes?: string, targetPrice?: number): Promise<WatchlistItem> {
    return this.request(`/api/watchlist/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        notes: notes ?? null,
        target_price: targetPrice ?? null,
      }),
    });
  }

  async removeFromWatchlist(id: number): Promise<void> {
    await this.request(`/api/watchlist/${id}`, { method: 'DELETE' });
  }

  async syncWatchlist(force: boolean = false): Promise<{ synced: number; errors: number; message: string }> {
    return this.request(`/api/watchlist/sync?force=${force}`, { method: 'POST' });
  }

  // Dividend endpoints
  async getDividendSummary(): Promise<DividendSummaryResponse> {
    return this.request<DividendSummaryResponse>('/api/dividends/summary');
  }

  async syncDividends(): Promise<{ status: string; message: string }> {
    return this.request('/api/dividends/sync', { method: 'POST' });
  }

  // Tax endpoints
  async getTaxReport(year: number): Promise<TaxReport> {
    return this.request<TaxReport>(`/api/tax/report?year=${year}`);
  }

  /** Absolute URL for the CSV download (used as an <a href> target). */
  getTaxReportCsvUrl(year: number): string {
    return `${this.baseUrl}/api/tax/report.csv?year=${year}`;
  }

  // Health check
  async healthCheck(): Promise<{ status: string }> {
    return this.request<{ status: string }>('/health');
  }
}

export const api = new ApiClient();
