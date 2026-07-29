import { useState, useMemo } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { BenchmarkDataset } from './PortfolioValueChart'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PortfolioValueChart } from './PortfolioValueChart'
import { PortfolioSummaryCards } from './PortfolioSummaryCards'
import { PerformanceMetricsCards } from './PerformanceMetricsCards'
import { ContributionsStrip } from './ContributionsStrip'
import { PositionsList } from './PositionsList'
import { PerformanceAttribution } from './PerformanceAttribution'
import { MonthlyReturnsHeatmap } from './MonthlyReturnsHeatmap'
import { DividendSummary } from './DividendSummary'
import { AllocationTab } from './AllocationTab'
import { ForecastTab } from './ForecastTab'
import { FundamentalsTab } from './FundamentalsTab'
import { WatchlistTab } from './WatchlistTab'
import { TaxTab } from './TaxTab'
import { DividendsTab } from './DividendsTab'
import { ThemeToggle } from './ThemeToggle'
import { BenchmarkPicker, BENCHMARK_COLORS } from './BenchmarkPicker'
import { useBaseCurrency, useCurrencySymbol } from '@/lib/CurrencyContext'
import { concentrationPct, maxDrawdownPct, sharpeRatio } from '@/lib/portfolioKpis'
import { RefreshCw, Download, Clock } from 'lucide-react'

type TimeRange = '1W' | 'MTD' | '1M' | '3M' | '6M' | 'YTD' | '1Y' | '2Y' | 'ALL'

export function Dashboard() {
  const queryClient = useQueryClient()
  const { baseCurrency, supportedCurrencies, setBaseCurrency, isUpdating: currencyUpdating, updateError: currencyError } = useBaseCurrency()
  const curSym = useCurrencySymbol()
  const [selectedRange, setSelectedRange] = useState<TimeRange>('1Y')
  const [selectedBenchmarks, setSelectedBenchmarks] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('selectedBenchmarks')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })

  const handleBenchmarkChange = (keys: string[]) => {
    setSelectedBenchmarks(keys)
    localStorage.setItem('selectedBenchmarks', JSON.stringify(keys))
  }

  const dateRange = useMemo(() => {
    const end = new Date().toISOString().split('T')[0]
    let start: string

    switch (selectedRange) {
      case '1W':
        start = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case 'MTD': {
        const now = new Date()
        start = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0]
        break
      }
      case '1M':
        start = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '3M':
        start = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '6M':
        start = new Date(Date.now() - 180 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case 'YTD': {
        const now = new Date()
        start = new Date(now.getFullYear(), 0, 1).toISOString().split('T')[0]
        break
      }
      case '1Y':
        start = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '2Y':
        start = new Date(Date.now() - 2 * 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case 'ALL':
        // First tax lot opened on 2024-05-28
        start = '2024-05-28'
        break
    }

    return { start, end }
  }, [selectedRange])

  // Fetch portfolio summary
  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['portfolio', 'summary'],
    queryFn: () => api.getPortfolioSummary(),
    staleTime: 30 * 60 * 1000,
  })

  // Fetch portfolio value over time
  const { data: valueOverTime, isLoading: chartLoading, isError: chartError } = useQuery({
    queryKey: ['portfolio', 'value-over-time', dateRange],
    queryFn: () => api.getPortfolioValueOverTime(dateRange.start, dateRange.end),
    staleTime: 30 * 60 * 1000,
  })

  // Fetch positions
  const { data: positions, isLoading: positionsLoading } = useQuery({
    queryKey: ['portfolio', 'positions'],
    queryFn: () => api.getPositions(),
  })

  // Fetch average monthly contributions
  const { data: contributions, isLoading: contributionsLoading } = useQuery({
    queryKey: ['portfolio', 'contributions'],
    queryFn: () => api.getContributions(),
    staleTime: 30 * 60 * 1000,
  })

  // Fetch benchmark comparisons (dynamic based on selection)
  const benchmarkQueries = useQueries({
    queries: selectedBenchmarks.map((key) => ({
      queryKey: ['portfolio', 'benchmark', dateRange, key],
      queryFn: () => api.getBenchmarkComparison(dateRange.start, dateRange.end, key),
      enabled: !!dateRange.start && !!dateRange.end,
      staleTime: 30 * 60 * 1000,
    })),
  })

  const benchmarkDatasets: BenchmarkDataset[] = useMemo(() => {
    return selectedBenchmarks
      .map((key, i) => {
        const query = benchmarkQueries[i]
        if (!query?.data) return null
        return {
          key,
          name: query.data.benchmark_name,
          color: BENCHMARK_COLORS[i % BENCHMARK_COLORS.length],
          data: query.data.data,
        }
      })
      .filter((d): d is BenchmarkDataset => d !== null)
  }, [selectedBenchmarks, benchmarkQueries])

  // Fetch XIRR annualized return for selected time range
  const { data: annualizedReturn, isLoading: xirrLoading } = useQuery({
    queryKey: ['portfolio', 'annualized-return', dateRange],
    queryFn: () => api.getAnnualizedReturn(dateRange.start, dateRange.end),
    enabled: !!dateRange.start && !!dateRange.end,
    staleTime: 30 * 60 * 1000,
  })

  // Fetch performance attribution for selected time range
  const { data: attribution, isLoading: attributionLoading } = useQuery({
    queryKey: ['portfolio', 'attribution', dateRange],
    queryFn: () => api.getPerformanceAttribution(dateRange.start, dateRange.end),
    enabled: !!dateRange.start && !!dateRange.end,
    staleTime: 30 * 60 * 1000,
  })

  // Fetch scheduler status (poll every 60s)
  const { data: schedulerStatus } = useQuery({
    queryKey: ['scheduler', 'status'],
    queryFn: () => api.getSchedulerStatus(),
    refetchInterval: 60_000,
  })

  // Calculate performance metrics for selected timeframe
  const performanceMetrics = useMemo(() => {
    if (!valueOverTime || valueOverTime.length === 0) {
      return null
    }

    const firstPoint = valueOverTime[0]
    const lastPoint = valueOverTime[valueOverTime.length - 1]

    const startValue = firstPoint.market_value_eur
    const currentValue = lastPoint.market_value_eur
    const absoluteChange = currentValue - startValue
    const percentageChange = startValue > 0 ? (absoluteChange / startValue) * 100 : 0

    // Period gain. The attribution endpoint already computes the period's
    // economic P&L over the same range — value change plus disposal proceeds
    // minus new investment — so it counts a realized gain. The local fallback
    // is the change in UNREALIZED profit, which drops when a winner is sold:
    // the gain leaves the unrealized pool and shows up nowhere.
    const startProfit = firstPoint.market_value_eur - firstPoint.cost_basis_eur
    const currentProfit = lastPoint.market_value_eur - lastPoint.cost_basis_eur
    const periodGain = attribution?.total_pnl_eur ?? (currentProfit - startProfit)
    // Use cost basis as denominator for gain % (more meaningful than profit-on-profit)
    const startCostBasis = firstPoint.cost_basis_eur
    const periodGainPercent = startCostBasis > 0 ? (periodGain / startCostBasis) * 100 : 0

    return {
      startValue,
      currentValue,
      absoluteChange,
      percentageChange,
      startDate: firstPoint.date,
      endDate: lastPoint.date,
      periodGain,
      periodGainPercent,
    }
  }, [valueOverTime, attribution])

  // Calculate KPIs
  const kpiMetrics = useMemo(() => {
    if (!valueOverTime || valueOverTime.length < 2 || !positions) {
      return null
    }

    // 1. Annual Return (XIRR) - from backend, fallback to null
    const xirr = annualizedReturn?.annualized_return_pct ?? null
    // "simple_period" for <30-day windows: a raw period return, not annualized.
    const xirrMethod = annualizedReturn?.method ?? 'xirr'

    // 2/3. Drawdown and Sharpe, from flow-adjusted daily returns. Extracted and
    // unit-tested: both net out the day's external flow, and inferring that flow
    // from the cost-basis line booked every profitable sale as a loss.
    const maxDrawdown = maxDrawdownPct(valueOverTime)
    const sharpe = sharpeRatio(valueOverTime)

    // 4. Win Rate (percentage of profitable positions)
    const profitablePositions = positions.filter(p => p.gain_loss_eur > 0).length
    const winRate = positions.length > 0 ? (profitablePositions / positions.length) * 100 : 0

    // 5. Calmar Ratio (XIRR / |Max Drawdown|) — needs an ANNUALIZED numerator,
    // so it goes blank on short ranges where only a period return exists.
    const calmarRatio = xirr !== null && xirrMethod === 'xirr' && maxDrawdown < 0
      ? xirr / Math.abs(maxDrawdown)
      : null

    // 6. Top 5 Concentration
    const top5Weight = concentrationPct(positions, 5)

    return {
      xirr,
      xirrMethod,
      maxDrawdown,
      sharpeRatio: sharpe,
      winRate,
      profitablePositions,
      totalPositions: positions.length,
      calmarRatio,
      top5Weight,
    }
  }, [valueOverTime, positions, annualizedReturn])

  // Sync mutation
  const syncMutation = useMutation({
    mutationFn: () => api.syncIBKRData(),
    onSuccess: () => {
      // Invalidate all queries to refresh data
      queryClient.invalidateQueries({ queryKey: ['portfolio'] })
    },
  })

  const handleSync = () => {
    syncMutation.mutate()
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b">
        <div className="w-full px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Portfolio Analyzer</h1>
              <p className="text-muted-foreground mt-1">
                Track your IBKR portfolio with cost basis and market value
              </p>
              {schedulerStatus && schedulerStatus.status === 'running' && (
                <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {schedulerStatus.last_sync ? (
                    <span>
                      Last sync: {new Date(schedulerStatus.last_sync.timestamp).toLocaleString()} ({schedulerStatus.last_sync.status})
                    </span>
                  ) : (
                    <span>No sync has run yet</span>
                  )}
                  {schedulerStatus.jobs.length > 0 && schedulerStatus.jobs[0].next_run_time && (
                    <span>
                      · Next: {new Date(schedulerStatus.jobs[0].next_run_time).toLocaleString()}
                    </span>
                  )}
                </div>
              )}
              {/* A bare "(error)" isn't actionable — show what actually went wrong. */}
              {schedulerStatus?.last_sync?.status === 'error' && schedulerStatus.last_sync.message && (
                <p className="mt-1 max-w-3xl text-xs text-amber-700 dark:text-amber-400">
                  {schedulerStatus.last_sync.message}
                </p>
              )}
              {/* Warnings ride on SUCCESSFUL runs (stale prices, skipped lots,
                  reclassified transfers) — they were computed and persisted but
                  never rendered anywhere, which is how a mispriced position once
                  went unnoticed for months. */}
              {(schedulerStatus?.last_sync?.warnings?.length ?? 0) > 0 && (
                <details className="mt-1 max-w-3xl">
                  <summary className="cursor-pointer text-xs font-medium text-amber-700 dark:text-amber-400">
                    ⚠ {schedulerStatus?.last_sync?.warnings?.length} warning
                    {(schedulerStatus?.last_sync?.warnings?.length ?? 0) > 1 ? 's' : ''} from the
                    last sync
                  </summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-amber-700/90 dark:text-amber-400/90">
                    {(schedulerStatus?.last_sync?.warnings ?? []).map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
            <div className="flex gap-2 items-center">
              <select
                value={baseCurrency}
                onChange={(e) => setBaseCurrency(e.target.value)}
                disabled={currencyUpdating}
                title="Base currency"
                className="h-9 rounded-md border border-input bg-background px-3 text-sm font-medium disabled:opacity-50"
              >
                {supportedCurrencies.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              {currencyError && (
                <span className="max-w-[12rem] text-xs leading-tight text-red-600 dark:text-red-400" role="alert">
                  {currencyError}
                </span>
              )}
              <ThemeToggle />
              <Button
                onClick={handleSync}
                disabled={syncMutation.isPending}
                variant="outline"
              >
                {syncMutation.isPending ? (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    Syncing...
                  </>
                ) : (
                  <>
                    <Download className="mr-2 h-4 w-4" />
                    Sync IBKR Data
                  </>
                )}
              </Button>
            </div>
          </div>

          {/* Sync status messages */}
          {syncMutation.isSuccess && (
            <div className="mt-4 p-4 bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 rounded-lg">
              <p className="text-sm text-green-800 dark:text-green-200">
                ✓ Sync successful! Securities: {syncMutation.data.securities_synced}, Tax Lots: {syncMutation.data.taxlots_synced}
              </p>
              {syncMutation.data.warnings && syncMutation.data.warnings.length > 0 && (
                <div className="mt-2">
                  {syncMutation.data.warnings.map((warning, i) => (
                    <p key={i} className="text-sm text-yellow-800 dark:text-yellow-200">
                      ⚠ {warning}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          {syncMutation.isError && (
            <div className="mt-4 p-4 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg">
              <p className="text-sm text-red-800 dark:text-red-200">
                ✗ Sync failed: {syncMutation.error.message}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="w-full px-4 py-6">
        <Tabs defaultValue="performance" className="space-y-8">
          <TabsList className="grid w-full max-w-3xl grid-cols-7">
            <TabsTrigger value="performance">Performance</TabsTrigger>
            <TabsTrigger value="allocation">Allocation</TabsTrigger>
            <TabsTrigger value="dividends">Dividends</TabsTrigger>
            <TabsTrigger value="fundamentals">Fundamentals</TabsTrigger>
            <TabsTrigger value="watchlist">Watchlist</TabsTrigger>
            <TabsTrigger value="forecast">Forecast</TabsTrigger>
            <TabsTrigger value="tax">Tax</TabsTrigger>
          </TabsList>

          {/* Performance Tab */}
          <TabsContent value="performance" className="space-y-8">
            {/* Summary Cards */}
            <PortfolioSummaryCards summary={summary} isLoading={summaryLoading} isError={summaryError} />

            {/* Performance Metrics - Time-Filtered KPIs */}
            <PerformanceMetricsCards
              metrics={kpiMetrics}
              isLoading={chartLoading || positionsLoading || xirrLoading}
            />

            {/* Portfolio Value Chart */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Portfolio Value Over Time</CardTitle>
                    <CardDescription>
                      Cost basis (invested) vs Market value (current worth) in {baseCurrency}
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1">
                      {(['1W', 'MTD', '1M', '3M', '6M', 'YTD', '1Y', '2Y', 'ALL'] as TimeRange[]).map((range) => (
                        <Button
                          key={range}
                          variant={selectedRange === range ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => setSelectedRange(range)}
                        >
                          {range}
                        </Button>
                      ))}
                    </div>
                    <BenchmarkPicker
                      selected={selectedBenchmarks}
                      onChange={handleBenchmarkChange}
                    />
                  </div>
                </div>
                {/* Period metrics on the left, average money added on the right — the
                    contributions strip lives here rather than in a card of its own, and
                    sits outside the performanceMetrics guard so it survives without them. */}
                <div className="mt-4 flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
                {performanceMetrics && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-6 text-sm">
                      <div className="flex items-center gap-2">
                        <span
                          className="text-muted-foreground"
                          title="Change in total holdings value over the period. This includes money you added — it is not a return; see Period Gain for that."
                        >
                          Value change:
                        </span>
                        <span className={`font-semibold ${performanceMetrics.absoluteChange >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          {performanceMetrics.absoluteChange >= 0 ? '+' : ''}{curSym}{performanceMetrics.absoluteChange.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <span className={`font-semibold ${performanceMetrics.percentageChange >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          ({performanceMetrics.percentageChange >= 0 ? '+' : ''}{performanceMetrics.percentageChange.toFixed(2)}%)
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-6 text-sm">
                      <div className="flex items-center gap-2">
                        <span
                          className="text-muted-foreground"
                          title="What the holdings actually earned over the period: value change plus proceeds of anything sold, less money put in. Realized gains count."
                        >
                          Period Gain:
                        </span>
                        <span className={`font-semibold ${performanceMetrics.periodGain >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          {performanceMetrics.periodGain >= 0 ? '+' : ''}{curSym}{performanceMetrics.periodGain.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <span className={`font-semibold ${performanceMetrics.periodGainPercent >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          ({performanceMetrics.periodGainPercent >= 0 ? '+' : ''}{performanceMetrics.periodGainPercent.toFixed(2)}%)
                        </span>
                      </div>
                    </div>
                  </div>
                )}
                  <ContributionsStrip data={contributions} isLoading={contributionsLoading} />
                </div>
              </CardHeader>
              <CardContent>
                <PortfolioValueChart
                  data={valueOverTime || []}
                  benchmarks={benchmarkDatasets}
                  isLoading={chartLoading}
                  isError={chartError}
                />
              </CardContent>
            </Card>

            {/* Monthly Returns Heatmap */}
            <MonthlyReturnsHeatmap data={valueOverTime} isLoading={chartLoading} />

            {/* Dividend Income Heatmap */}
            <DividendSummary />

            {/* Performance Attribution */}
            <PerformanceAttribution data={attribution} isLoading={attributionLoading} />

            {/* Positions Table */}
            <PositionsList positions={positions || []} isLoading={positionsLoading} />
          </TabsContent>

          {/* Allocation Tab */}
          <TabsContent value="allocation">
            <AllocationTab />
          </TabsContent>

          {/* Dividends Tab */}
          <TabsContent value="dividends">
            <DividendsTab />
          </TabsContent>

          {/* Fundamentals Tab */}
          <TabsContent value="fundamentals">
            <FundamentalsTab />
          </TabsContent>

          {/* Watchlist Tab */}
          <TabsContent value="watchlist">
            <WatchlistTab />
          </TabsContent>

          {/* Forecast Tab */}
          <TabsContent value="forecast">
            <ForecastTab />
          </TabsContent>

          {/* Tax Tab */}
          <TabsContent value="tax">
            <TaxTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
