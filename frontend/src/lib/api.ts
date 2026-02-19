/**
 * API Client for IBKR Portfolio Analyzer Backend
 */

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface PortfolioValuePoint {
  date: string;
  cost_basis_eur: number;
  market_value_eur: number;
  gain_loss_eur: number;
  gain_loss_percent: number;
}

export interface PortfolioSummary {
  total_cost_basis_eur: number;
  total_market_value_eur: number;
  total_gain_loss_eur: number;
  total_gain_loss_percent: number;
  num_positions: number;
  date?: string;
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

export interface SyncResponse {
  message: string;
  securities_synced: number;
  taxlots_synced: number;
  warnings?: string[];
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

  async getPositions(): Promise<Position[]> {
    return this.request<Position[]>('/api/portfolio/positions');
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

  async getPortfolioAllocation(): Promise<{
    sector_allocation: Record<string, number>;
    geographic_allocation: Record<string, number>;
    asset_type_allocation: Record<string, number>;
  }> {
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

  // Health check
  async healthCheck(): Promise<{ status: string }> {
    return this.request<{ status: string }>('/health');
  }
}

export const api = new ApiClient();
