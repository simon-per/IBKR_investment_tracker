import { Activity, Gauge, Layers, Scale, TrendingDown } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

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

/** A dash, not a zero — every absent metric here means "unknown", never "none". */
function Absent() {
  return <div className="text-2xl font-bold text-muted-foreground">—</div>
}

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
      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
        {[1, 2, 3, 4, 5].map((i) => (
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

  const { beta } = metrics
  // The current fall is the one that describes now; the max describes the worst
  // the account has survived. Showing only the max reads as a live warning long
  // after the recovery.
  const inDrawdown = metrics.currentDrawdownPct < -0.05

  return (
    <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
      {/* Volatility */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Volatility</CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          {metrics.volatilityPct !== null ? (
            <div className="text-2xl font-bold">{metrics.volatilityPct.toFixed(1)}%</div>
          ) : (
            <Absent />
          )}
          <p className="text-xs text-muted-foreground">
            {metrics.volatilityPct !== null
              ? 'Annualised, the risk Sharpe divides by'
              : 'Not enough history in this range'}
          </p>
        </CardContent>
      </Card>

      {/* Sortino */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Sortino Ratio</CardTitle>
          <Gauge className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          {metrics.sortino !== null ? (
            <div
              className={`text-2xl font-bold ${
                metrics.sortino >= 1
                  ? 'text-green-600'
                  : metrics.sortino >= 0
                    ? 'text-yellow-600'
                    : 'text-red-600'
              }`}
            >
              {metrics.sortino.toFixed(2)}
            </div>
          ) : (
            <Absent />
          )}
          <p className="text-xs text-muted-foreground">
            {metrics.sortino !== null
              ? 'Return per unit of downside only'
              : 'No down days to measure against'}
          </p>
        </CardContent>
      </Card>

      {/* Beta vs the primary benchmark */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Beta</CardTitle>
          <Scale className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          {beta?.beta != null ? (
            <div className="text-2xl font-bold">{beta.beta.toFixed(2)}</div>
          ) : (
            <Absent />
          )}
          <p className="text-xs text-muted-foreground">
            {beta === null
              ? 'Pick a benchmark to compare against'
              : beta.beta === null
                ? `Needs ${beta.minSampleDays} flow-free days (${beta.sampleDays} so far)`
                : `vs ${beta.benchmarkName}${
                    beta.correlation !== null ? ` · r ${beta.correlation.toFixed(2)}` : ''
                  }`}
          </p>
        </CardContent>
      </Card>

      {/* Current drawdown, with the worst one for context */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Current Drawdown</CardTitle>
          <TrendingDown
            className={`h-4 w-4 ${inDrawdown ? 'text-red-600' : 'text-muted-foreground'}`}
          />
        </CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold ${inDrawdown ? 'text-red-600' : 'text-green-600'}`}>
            {metrics.currentDrawdownPct.toFixed(2)}%
          </div>
          <p className="text-xs text-muted-foreground">
            {metrics.maxDrawdownPct === 0
              ? 'Never below its opening value'
              : metrics.recoveredDate !== null
                ? `Recovered ${shortDate(metrics.recoveredDate)} from ${metrics.maxDrawdownPct.toFixed(1)}%`
                : `Worst ${metrics.maxDrawdownPct.toFixed(1)}%${
                    metrics.troughDate ? ` on ${shortDate(metrics.troughDate)}` : ''
                  }`}
          </p>
        </CardContent>
      </Card>

      {/* Effective holdings */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Effective Holdings</CardTitle>
          <Layers className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          {metrics.effectiveHoldings !== null ? (
            <div className="text-2xl font-bold">{metrics.effectiveHoldings.toFixed(1)}</div>
          ) : (
            <Absent />
          )}
          <p className="text-xs text-muted-foreground">
            {metrics.effectiveHoldings !== null
              ? `of ${metrics.totalPositions} held, by weight`
              : 'No priced positions'}
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
