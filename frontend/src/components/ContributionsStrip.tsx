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
 * Average capital deployed per month, over all time / 12M / 6M / 3M, each trailing
 * window shown as a delta against the all-time average — the comparison that
 * reveals a slowing rate of investment.
 *
 * Deployed (primary) is the cost basis of the lots opened in each month. It spans
 * the whole history including the pre-IBKR years, because the broker transfer
 * carried every lot across with its original date and cost basis.
 *
 * Added (secondary) is real deposits, which are strictly more accurate but only
 * exist from `deposits_from` onward — earlier deposits went to the previous
 * brokers. It is rendered only for windows it actually covers; showing it for the
 * rest would read as "you saved nothing", which is the opposite of the truth.
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
  const showAdded = data.windows.some(w => w.added_covered)

  const labelTitle = data.deposits_from
    ? `Deployed is the cost basis of the lots bought in each period — it covers the whole `
      + `history, including the holdings transferred in`
      + (data.transfer_in_date ? ` on ${data.transfer_in_date}` : '')
      + `, which kept their original purchase dates. Added is real deposits, known only `
      + `from ${data.deposits_from} onward because earlier deposits went to the previous `
      + `broker; transfers are never counted as added.`
    : `Cost basis of the lots bought in each period, at the exchange rate on each `
      + `purchase date. Enable 'Deposits & Withdrawals' on the Flex Query to also see `
      + `real deposits.`

  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex flex-wrap items-start gap-x-10 gap-y-4">
          <div className="flex items-center gap-2 pt-1" title={labelTitle}>
            <PiggyBank className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">Avg Monthly Invested</span>
          </div>

          {data.windows.map(w => {
            const delta = w.label !== 'all' && baseline !== 0
              ? ((w.avg_per_month_eur - baseline) / Math.abs(baseline)) * 100
              : null

            const title = [
              `${WINDOW_LABELS[w.label]}: ${formatCurrency(w.gross_eur)} deployed over ${w.months.toFixed(1)} months`,
              `${formatCurrency(w.net_eur)} of that is still invested after sales`,
              w.partial ? `* only ${w.months.toFixed(1)} months of history available` : null,
              w.added_covered && w.added_eur !== null
                ? `${formatCurrency(w.added_eur)} actually deposited over the same period`
                : null,
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
                {showAdded && (
                  <div className="text-xs tabular-nums text-muted-foreground">
                    {w.added_covered && w.avg_added_per_month_eur !== null
                      ? `${formatCurrency(w.avg_added_per_month_eur)} in`
                      : <span className="opacity-60">—</span>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
