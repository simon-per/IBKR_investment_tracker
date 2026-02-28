import { TrendingUp, TrendingDown, Activity, Target } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface PerformanceMetricsCardsProps {
  metrics: {
    xirr: number | null
    maxDrawdown: number
    sharpeRatio: number
    winRate: number
    profitablePositions: number
    totalPositions: number
  } | null
  isLoading?: boolean
}

export function PerformanceMetricsCards({ metrics, isLoading }: PerformanceMetricsCardsProps) {
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Loading...</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-8 bg-muted animate-pulse rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  if (!metrics) {
    return null
  }

  const isPositiveXIRR = metrics.xirr !== null && metrics.xirr >= 0
  const isPositiveSharpe = metrics.sharpeRatio >= 0

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {/* Annual Return (XIRR) */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Annual Return (XIRR)</CardTitle>
          {isPositiveXIRR ? (
            <TrendingUp className="h-4 w-4 text-green-600" />
          ) : (
            <TrendingDown className="h-4 w-4 text-red-600" />
          )}
        </CardHeader>
        <CardContent>
          {metrics.xirr !== null ? (
            <div className={`text-2xl font-bold ${isPositiveXIRR ? 'text-green-600' : 'text-red-600'}`}>
              {isPositiveXIRR ? '+' : ''}{metrics.xirr.toFixed(2)}%
            </div>
          ) : (
            <div className="text-2xl font-bold text-muted-foreground">N/A</div>
          )}
          <p className="text-xs text-muted-foreground">
            Money-weighted, adjusted for deposits
          </p>
        </CardContent>
      </Card>

      {/* Max Drawdown */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Max Drawdown</CardTitle>
          <TrendingDown className="h-4 w-4 text-red-600" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold text-red-600">
            {metrics.maxDrawdown.toFixed(2)}%
          </div>
          <p className="text-xs text-muted-foreground">
            Largest peak-to-trough decline
          </p>
        </CardContent>
      </Card>

      {/* Sharpe Ratio */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Sharpe Ratio</CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold ${isPositiveSharpe ? 'text-green-600' : 'text-red-600'}`}>
            {metrics.sharpeRatio.toFixed(2)}
          </div>
          <p className="text-xs text-muted-foreground">
            Risk-adjusted return
          </p>
        </CardContent>
      </Card>

      {/* Win Rate */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Win Rate</CardTitle>
          <Target className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">
            {metrics.winRate.toFixed(1)}%
          </div>
          <p className="text-xs text-muted-foreground">
            {metrics.profitablePositions} of {metrics.totalPositions} profitable
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
