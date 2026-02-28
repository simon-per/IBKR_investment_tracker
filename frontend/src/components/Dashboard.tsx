import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PortfolioValueChart } from './PortfolioValueChart'
import { PortfolioSummaryCards } from './PortfolioSummaryCards'
import { PerformanceMetricsCards } from './PerformanceMetricsCards'
import { PositionsList } from './PositionsList'
import { AllocationTab } from './AllocationTab'
import { ForecastTab } from './ForecastTab'
import { ThemeToggle } from './ThemeToggle'
import { RefreshCw, Download, Clock } from 'lucide-react'

type TimeRange = '1W' | '1M' | '3M' | '6M' | '1Y' | '2Y' | '3Y' | '5Y' | 'ALL'

export function Dashboard() {
  const queryClient = useQueryClient()
  const [selectedRange, setSelectedRange] = useState<TimeRange>('1Y')

  const dateRange = useMemo(() => {
    const end = new Date().toISOString().split('T')[0]
    let start: string

    switch (selectedRange) {
      case '1W':
        start = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '1M':
        start = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '3M':
        start = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '6M':
        start = new Date(Date.now() - 180 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '1Y':
        start = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '2Y':
        start = new Date(Date.now() - 2 * 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '3Y':
        start = new Date(Date.now() - 3 * 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case '5Y':
        start = new Date(Date.now() - 5 * 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
        break
      case 'ALL':
        // First tax lot opened on 2024-05-28
        start = '2024-05-28'
        break
    }

    return { start, end }
  }, [selectedRange])

  // Fetch portfolio summary
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['portfolio', 'summary'],
    queryFn: () => api.getPortfolioSummary(),
  })

  // Fetch portfolio value over time
  const { data: valueOverTime, isLoading: chartLoading } = useQuery({
    queryKey: ['portfolio', 'value-over-time', dateRange],
    queryFn: () => api.getPortfolioValueOverTime(dateRange.start, dateRange.end),
  })

  // Fetch positions
  const { data: positions, isLoading: positionsLoading } = useQuery({
    queryKey: ['portfolio', 'positions'],
    queryFn: () => api.getPositions(),
  })

  // Fetch XIRR annualized return for selected time range
  const { data: annualizedReturn, isLoading: xirrLoading } = useQuery({
    queryKey: ['portfolio', 'annualized-return', dateRange],
    queryFn: () => api.getAnnualizedReturn(dateRange.start, dateRange.end),
    enabled: !!dateRange.start && !!dateRange.end,
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

    // Calculate period gain (profit change over the time period)
    const startProfit = firstPoint.market_value_eur - firstPoint.cost_basis_eur
    const currentProfit = lastPoint.market_value_eur - lastPoint.cost_basis_eur
    const periodGain = currentProfit - startProfit
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
  }, [valueOverTime])

  // Calculate KPIs
  const kpiMetrics = useMemo(() => {
    if (!valueOverTime || valueOverTime.length < 2 || !positions) {
      return null
    }

    // 1. Annual Return (XIRR) - from backend, fallback to null
    const xirr = annualizedReturn?.annualized_return_pct ?? null

    // 2. Maximum Drawdown
    let maxDrawdown = 0
    let peak = valueOverTime[0].market_value_eur

    for (const point of valueOverTime) {
      const value = point.market_value_eur
      if (value > peak) {
        peak = value
      }
      if (peak > 0) {
        const drawdown = ((value - peak) / peak) * 100
        if (drawdown < maxDrawdown) {
          maxDrawdown = drawdown
        }
      }
    }

    // 3. Sharpe Ratio
    // Calculate daily returns (need at least 2 data points for returns)
    const returns: number[] = []
    for (let i = 1; i < valueOverTime.length; i++) {
      const prevValue = valueOverTime[i - 1].market_value_eur
      const currValue = valueOverTime[i].market_value_eur
      if (prevValue > 0) {
        const dailyReturn = (currValue - prevValue) / prevValue
        returns.push(dailyReturn)
      }
    }

    let sharpeRatio = 0
    if (returns.length >= 5) {
      // Calculate average return and standard deviation
      const avgReturn = returns.reduce((sum, r) => sum + r, 0) / returns.length
      const variance = returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / returns.length
      const stdDev = Math.sqrt(variance)

      // Annualize (assuming ~252 trading days per year)
      const annualizedReturn = avgReturn * 252
      const annualizedStdDev = stdDev * Math.sqrt(252)

      // Risk-free rate (assume 3% for EUR)
      const riskFreeRate = 0.03

      sharpeRatio = annualizedStdDev > 0.001
        ? (annualizedReturn - riskFreeRate) / annualizedStdDev
        : 0

      // Clamp to reasonable range
      sharpeRatio = Math.max(-10, Math.min(10, sharpeRatio))
    }

    // 4. Win Rate (percentage of profitable positions)
    const profitablePositions = positions.filter(p => p.gain_loss_eur > 0).length
    const winRate = positions.length > 0 ? (profitablePositions / positions.length) * 100 : 0

    return {
      xirr,
      maxDrawdown,
      sharpeRatio,
      winRate,
      profitablePositions,
      totalPositions: positions.length,
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
        <div className="container mx-auto px-4 py-6">
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
            </div>
            <div className="flex gap-2">
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
      <div className="container mx-auto px-4 py-8">
        <Tabs defaultValue="performance" className="space-y-8">
          <TabsList className="grid w-full max-w-md grid-cols-3">
            <TabsTrigger value="performance">Performance</TabsTrigger>
            <TabsTrigger value="allocation">Allocation</TabsTrigger>
            <TabsTrigger value="forecast">Forecast</TabsTrigger>
          </TabsList>

          {/* Performance Tab */}
          <TabsContent value="performance" className="space-y-8">
            {/* Summary Cards */}
            <PortfolioSummaryCards summary={summary} isLoading={summaryLoading} />

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
                      Cost basis (invested) vs Market value (current worth) in EUR
                    </CardDescription>
                  </div>
                  <div className="flex gap-1">
                    {(['1W', '1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', 'ALL'] as TimeRange[]).map((range) => (
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
                </div>
                {performanceMetrics && (
                  <div className="mt-4 space-y-2">
                    <div className="flex items-center gap-6 text-sm">
                      <div className="flex items-center gap-2">
                        <span className="text-muted-foreground">Period Performance:</span>
                        <span className={`font-semibold ${performanceMetrics.absoluteChange >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          {performanceMetrics.absoluteChange >= 0 ? '+' : ''}€{performanceMetrics.absoluteChange.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <span className={`font-semibold ${performanceMetrics.percentageChange >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          ({performanceMetrics.percentageChange >= 0 ? '+' : ''}{performanceMetrics.percentageChange.toFixed(2)}%)
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-6 text-sm">
                      <div className="flex items-center gap-2">
                        <span className="text-muted-foreground">Period Gain:</span>
                        <span className={`font-semibold ${performanceMetrics.periodGain >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          {performanceMetrics.periodGain >= 0 ? '+' : ''}€{performanceMetrics.periodGain.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <span className={`font-semibold ${performanceMetrics.periodGainPercent >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                          ({performanceMetrics.periodGainPercent >= 0 ? '+' : ''}{performanceMetrics.periodGainPercent.toFixed(2)}%)
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                <PortfolioValueChart data={valueOverTime || []} isLoading={chartLoading} />
              </CardContent>
            </Card>

            {/* Positions Table */}
            <PositionsList positions={positions || []} isLoading={positionsLoading} />
          </TabsContent>

          {/* Allocation Tab */}
          <TabsContent value="allocation">
            <AllocationTab />
          </TabsContent>

          {/* Forecast Tab */}
          <TabsContent value="forecast">
            <ForecastTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
