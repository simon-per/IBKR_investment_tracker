import { PiggyBank } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useFormatCurrency } from '@/lib/CurrencyContext'
import type { ContributionsResponse, ContributionWindow } from '@/lib/api'

interface ContributionsStripProps {
  data: ContributionsResponse | undefined
  isLoading?: boolean
}

const WINDOW_LABELS: Record<ContributionWindow['label'], string> = {
  all: 'All time',
  '12m': '12M',
  '6m': '6M',
  '3m': '3M',
}

/** Deltas inside this band are ordinary variation, not a trend worth colouring. */
const FLAT_BAND_PCT = 5

function deltaColor(pct: number): string {
  if (pct > FLAT_BAND_PCT) return 'text-green-600 dark:text-green-400'
  if (pct < -FLAT_BAND_PCT) return 'text-red-600 dark:text-red-400'
  return 'text-muted-foreground'
}

/**
 * Average money added to the account per month, over all time / 12M / 6M / 3M,
 * with each trailing window shown as a delta against the all-time average — the
 * comparison that reveals a savings rate slipping.
 *
 * Derived from tax lots, not deposits (the Flex Query carries none): capital
 * deployed minus capital released. See PortfolioService.get_contributions.
 */
export function ContributionsStrip({ data, isLoading }: ContributionsStripProps) {
  const formatCurrency = useFormatCurrency()

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-4">
          <div className="h-10 bg-muted animate-pulse rounded" />
        </CardContent>
      </Card>
    )
  }

  if (!data || data.windows.length === 0) return null

  const baseline = data.windows.find(w => w.label === 'all')?.avg_per_month_eur ?? 0

  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex flex-wrap items-start gap-x-10 gap-y-4">
          <div className="flex items-center gap-2 pt-1">
            <PiggyBank className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">Avg Monthly Contribution</span>
          </div>

          {data.windows.map(w => {
            const delta = w.label !== 'all' && baseline !== 0
              ? ((w.avg_per_month_eur - baseline) / Math.abs(baseline)) * 100
              : null

            const title = [
              `${WINDOW_LABELS[w.label]}: ${formatCurrency(w.net_eur)} net invested over ${w.months.toFixed(1)} months`,
              `${formatCurrency(w.gross_eur)} bought before sales`,
              w.partial ? `* only ${w.months.toFixed(1)} months of history available` : null,
              'Derived from tax lots, not cash deposits — proceeds from a sale that you have not reinvested yet count as a negative month.',
            ].filter(Boolean).join(' · ')

            return (
              <div key={w.label} title={title}>
                <div className="text-xs text-muted-foreground">
                  {WINDOW_LABELS[w.label]}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {formatCurrency(w.avg_per_month_eur)}
                  {w.partial && <span className="text-muted-foreground">*</span>}
                </div>
                <div className={cn('text-xs tabular-nums', delta === null ? 'invisible' : deltaColor(delta))}>
                  {delta !== null && `${delta >= 0 ? '+' : ''}${delta.toFixed(0)}%`}
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
