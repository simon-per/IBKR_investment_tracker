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
 * Money in per month, over all time / 12M / 6M / 3M, each trailing window shown as
 * a delta against the all-time average.
 *
 * The headline is spliced at the deposit-coverage boundary: lot cost basis for the
 * pre-IBKR years (which the broker transfer preserved with original dates and cost
 * basis), real deposits from there on. Deposits take over as soon as they exist
 * because lot cost basis cannot survive a rotation — selling one ETF to buy another
 * counts the same money twice.
 *
 * Deployed stays as a muted second line: once rotation starts it exceeds money in,
 * and that gap is capital churn rather than saving.
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

  const baseline = data.windows.find(w => w.label === 'all')?.avg_money_in_per_month_eur ?? 0

  const labelTitle = data.coverage_from
    ? `Real deposits from ${data.coverage_from} onward; before that, the cost basis of `
      + `the lots bought each month — which covers the pre-IBKR years because the `
      + `holdings transferred in`
      + (data.transfer_in_date ? ` on ${data.transfer_in_date}` : '')
      + ` kept their original purchase dates. Deposits take over where they exist `
      + `because selling one holding to buy another would otherwise count the same `
      + `money twice. Broker transfers are never counted as money in.`
    : `Cost basis of the lots bought in each period, at the exchange rate on each `
      + `purchase date. Enable 'Deposits & Withdrawals' on the Flex Query to measure `
      + `real deposits instead, which a position switch cannot inflate.`

  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex flex-wrap items-start gap-x-10 gap-y-4">
          <div className="flex items-center gap-2 pt-1" title={labelTitle}>
            <PiggyBank className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">Avg Monthly Contribution</span>
          </div>

          {data.windows.map(w => {
            const delta = w.label !== 'all' && baseline !== 0
              ? ((w.avg_money_in_per_month_eur - baseline) / Math.abs(baseline)) * 100
              : null

            const source = {
              deposits: 'real deposits',
              spliced: `purchases up to ${data.coverage_from}, then real deposits`,
              deployed: 'cost basis of purchases (no deposit ledger yet)',
            }[w.money_in_method]

            const title = [
              `${WINDOW_LABELS[w.label]}: ${formatCurrency(w.money_in_eur)} in over ${w.months.toFixed(1)} months, from ${source}`,
              w.money_in_method !== 'deployed'
                ? `${formatCurrency(w.deposits_eur)} of that is deposits`
                : null,
              `${formatCurrency(w.deployed_eur)} deployed into positions over the same period`
                + (w.deployed_eur > w.money_in_eur
                  ? ' — the excess is capital rotated between holdings, not new money'
                  : ''),
              w.partial ? `* only ${w.months.toFixed(1)} months of history available` : null,
            ].filter(Boolean).join(' · ')

            return (
              <div key={w.label} title={title}>
                <div className="text-xs text-muted-foreground">
                  {WINDOW_LABELS[w.label]}
                  {w.money_in_method === 'spliced' && (
                    <span className="ml-1 opacity-60" title="part purchases, part deposits">~</span>
                  )}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {formatCurrency(w.avg_money_in_per_month_eur)}
                  {w.partial && <span className="text-muted-foreground">*</span>}
                </div>
                <div className={cn('text-xs tabular-nums', delta === null ? 'invisible' : deltaColor(delta))}>
                  {delta !== null && `${delta >= 0 ? '+' : ''}${delta.toFixed(0)}%`}
                </div>
                <div className="text-xs tabular-nums text-muted-foreground">
                  {formatCurrency(w.avg_deployed_per_month_eur)} out
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
