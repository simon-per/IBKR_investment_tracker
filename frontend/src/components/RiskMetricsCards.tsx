import { Activity, Gauge, Layers, Scale, TrendingDown } from 'lucide-react'
import { KpiCard, KpiCardSkeleton } from '@/components/ui/KpiCard'

/**
 * Beta needs a benchmark, and there are three separate reasons it can be
 * absent — none of which should render as a number. `null` for the whole object
 * means nothing is selected to compare against; `beta: null` with a
 * `sampleDays` count means the window is too thin to regress.
 */
export interface RiskBeta {
  beta: number | null
  correlation: number | null
  sampleDays: number
  minSampleDays: number
  benchmarkName: string
}

export interface RiskMetrics {
  volatilityPct: number | null
  sortino: number | null
  currentDrawdownPct: number
  maxDrawdownPct: number
  troughDate: string | null
  recoveredDate: string | null
  effectiveHoldings: number | null
  totalPositions: number
  beta: RiskBeta | null
}

interface RiskMetricsCardsProps {
  metrics: RiskMetrics | null
  isLoading?: boolean
}

/**
 * A dash, not a zero — every absent metric here means "unknown", never "none". The rule
 * now lives in `KpiCard`: passing `value={null}` renders it, so the four files that each
 * had their own idea of an absent value (an em dash here, `N/A` in PerformanceMetrics)
 * cannot drift again.
 */

/** `2026-03-14` → `14 Mar` without dragging a locale into it. */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function shortDate(iso: string): string {
  const [, month, dayOfMonth] = iso.split('-')
  const monthName = MONTHS[Number(month) - 1]
  if (!monthName || !dayOfMonth) return iso
  return `${Number(dayOfMonth)} ${monthName}`
}

export function RiskMetricsCards({ metrics, isLoading }: RiskMetricsCardsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-5">
        <KpiCardSkeleton count={5} />
      </div>
    )
  }

  if (!metrics) {
    return null
  }

  const { beta } = metrics
  // The current fall is the one that describes now; the max describes the worst
  // the account has survived. Showing only the max reads as a live warning long
  // after the recovery.
  const inDrawdown = metrics.currentDrawdownPct < -0.05

  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-5">
      <KpiCard
        label="Volatility"
        icon={<Activity className="h-4 w-4 text-muted-foreground" />}
        value={metrics.volatilityPct !== null ? `${metrics.volatilityPct.toFixed(1)}%` : null}
        sub={metrics.volatilityPct !== null
          ? 'Annualised, the risk Sharpe divides by'
          : 'Not enough history in this range'}
      />

      <KpiCard
        label="Sortino Ratio"
        icon={<Gauge className="h-4 w-4 text-muted-foreground" />}
        value={metrics.sortino !== null ? metrics.sortino.toFixed(2) : null}
        tone={metrics.sortino === null ? 'muted'
          : metrics.sortino >= 1 ? 'positive'
          : metrics.sortino >= 0 ? 'warning'
          : 'negative'}
        sub={metrics.sortino !== null
          ? 'Return per unit of downside only'
          : 'No down days to measure against'}
      />

      {/* Beta vs the primary benchmark. Three distinct reasons it can be absent, and the
          footnote is what tells them apart — the value is a dash in all three. */}
      <KpiCard
        label="Beta"
        icon={<Scale className="h-4 w-4 text-muted-foreground" />}
        value={beta?.beta != null ? beta.beta.toFixed(2) : null}
        sub={beta === null
          ? 'Pick a benchmark to compare against'
          : beta.beta === null
            ? `Needs ${beta.minSampleDays} flow-free days (${beta.sampleDays} so far)`
            : `vs ${beta.benchmarkName}${
                beta.correlation !== null ? ` · r ${beta.correlation.toFixed(2)}` : ''
              }`}
      />

      {/* Current drawdown, with the worst one for context */}
      <KpiCard
        label="Current Drawdown"
        icon={<TrendingDown
          className={`h-4 w-4 ${inDrawdown ? 'text-red-600' : 'text-muted-foreground'}`}
        />}
        value={`${metrics.currentDrawdownPct.toFixed(2)}%`}
        tone={inDrawdown ? 'negative' : 'positive'}
        sub={metrics.maxDrawdownPct === 0
          ? 'Never below its opening value'
          : metrics.recoveredDate !== null
            ? `Recovered ${shortDate(metrics.recoveredDate)} from ${metrics.maxDrawdownPct.toFixed(1)}%`
            : `Worst ${metrics.maxDrawdownPct.toFixed(1)}%${
                metrics.troughDate ? ` on ${shortDate(metrics.troughDate)}` : ''
              }`}
      />

      <KpiCard
        label="Effective Holdings"
        icon={<Layers className="h-4 w-4 text-muted-foreground" />}
        value={metrics.effectiveHoldings !== null ? metrics.effectiveHoldings.toFixed(1) : null}
        sub={metrics.effectiveHoldings !== null
          ? `of ${metrics.totalPositions} held, by weight`
          : 'No priced positions'}
      />
    </div>
  )
}
