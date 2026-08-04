import { TrendingUp, TrendingDown, Activity, Target, Shield, PieChart } from 'lucide-react'
import { KpiCard, KpiCardSkeleton } from '@/components/ui/KpiCard'

interface PerformanceMetricsCardsProps {
  metrics: {
    xirr: number | null
    xirrMethod?: string
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
      <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-6">
        <KpiCardSkeleton count={6} />
      </div>
    )
  }

  if (!metrics) {
    return null
  }

  const isPositiveXIRR = metrics.xirr !== null && metrics.xirr >= 0
  const isPositiveSharpe = metrics.sharpeRatio >= 0

  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-6">
      {/* Annual Return (XIRR). A window under 30 days reports simple_period instead, and
          the label follows it rather than annualising a few days of noise. */}
      <KpiCard
        label={metrics.xirrMethod === 'simple_period' ? 'Period Return' : 'Annual Return (XIRR)'}
        icon={isPositiveXIRR
          ? <TrendingUp className="h-4 w-4 text-green-600" />
          : <TrendingDown className="h-4 w-4 text-red-600" />}
        value={metrics.xirr !== null
          ? `${isPositiveXIRR ? '+' : ''}${metrics.xirr.toFixed(2)}%`
          : null}
        tone={isPositiveXIRR ? 'positive' : 'negative'}
        sub="Money-weighted, adjusted for deposits"
      />

      <KpiCard
        label="Max Drawdown"
        icon={<TrendingDown className="h-4 w-4 text-red-600" />}
        value={`${metrics.maxDrawdown.toFixed(2)}%`}
        tone="negative"
        sub="Largest peak-to-trough decline"
      />

      <KpiCard
        label="Sharpe Ratio"
        icon={<Activity className="h-4 w-4 text-muted-foreground" />}
        value={metrics.sharpeRatio.toFixed(2)}
        tone={isPositiveSharpe ? 'positive' : 'negative'}
        sub="Risk-adjusted return"
      />

      <KpiCard
        label="Win Rate"
        icon={<Target className="h-4 w-4 text-muted-foreground" />}
        value={`${metrics.winRate.toFixed(1)}%`}
        sub={`${metrics.profitablePositions} of ${metrics.totalPositions} profitable`}
      />

      <KpiCard
        label="Calmar Ratio"
        icon={<Shield className="h-4 w-4 text-muted-foreground" />}
        value={metrics.calmarRatio !== null ? metrics.calmarRatio.toFixed(2) : null}
        tone={metrics.calmarRatio === null ? 'muted'
          : metrics.calmarRatio >= 1 ? 'positive'
          : metrics.calmarRatio >= 0 ? 'warning'
          : 'negative'}
        sub="Return / drawdown"
      />

      <KpiCard
        label="Top 5 Weight"
        icon={<PieChart className="h-4 w-4 text-muted-foreground" />}
        value={`${metrics.top5Weight.toFixed(1)}%`}
        tone={metrics.top5Weight > 70 ? 'negative'
          : metrics.top5Weight > 50 ? 'warning'
          : 'positive'}
        sub="Concentration risk"
      />
    </div>
  )
}
