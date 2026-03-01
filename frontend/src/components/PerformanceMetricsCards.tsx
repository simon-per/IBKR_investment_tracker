import { TrendingUp, TrendingDown, Activity, Target, Shield, PieChart } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface PerformanceMetricsCardsProps {
  metrics: {
    xirr: number | null
    maxDrawdown: number
    sharpeRatio: number
    winRate: number
    profitablePositions: number
    totalPositions: number
    calmarRatio: number | null
    top5Weight: number
  } | null
  isLoading?: boolean
}

export function PerformanceMetricsCards({ metrics, isLoading }: PerformanceMetricsCardsProps) {
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
        {[1, 2, 3, 4, 5, 6].map((i) => (
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
    <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
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

      {/* Calmar Ratio */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Calmar Ratio</CardTitle>
          <Shield className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          {metrics.calmarRatio !== null ? (
            <div className={`text-2xl font-bold ${metrics.calmarRatio >= 1 ? 'text-green-600' : metrics.calmarRatio >= 0 ? 'text-yellow-600' : 'text-red-600'}`}>
              {metrics.calmarRatio.toFixed(2)}
            </div>
          ) : (
            <div className="text-2xl font-bold text-muted-foreground">N/A</div>
          )}
          <p className="text-xs text-muted-foreground">
            Return / drawdown
          </p>
        </CardContent>
      </Card>

      {/* Top 5 Concentration */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Top 5 Weight</CardTitle>
          <PieChart className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold ${metrics.top5Weight > 70 ? 'text-red-600' : metrics.top5Weight > 50 ? 'text-yellow-600' : 'text-green-600'}`}>
            {metrics.top5Weight.toFixed(1)}%
          </div>
          <p className="text-xs text-muted-foreground">
            Concentration risk
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
