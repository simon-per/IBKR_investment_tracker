import { PiggyBank } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCurrencySymbol, useFormatCurrency } from '@/lib/CurrencyContext'
import { deltaColor } from '@/lib/delta'
import type { ContributionsResponse, ContributionWindow } from '@/lib/api'

interface ContributionsStripProps {
  data: ContributionsResponse | undefined
  isLoading?: boolean
  isError?: boolean
}

const WINDOW_LABELS: Record<ContributionWindow['label'], string> = {
  all: 'All time',
  '12m': '12M',
  '6m': '6M',
  '3m': '3M',
}

/** Whole units: cents on a monthly average are noise, and the tooltip keeps the exact figure. */
function round(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

/**
 * Money in per month, over all time / 12M / 6M / 3M, each trailing window shown as
 * a delta against the all-time average.
 *
 * Rendered inline inside the Portfolio Value Over Time card header, beside the period
 * metrics — two lines, no card of its own.
 *
 * The headline is spliced at the deposit-coverage boundary: lot cost basis for the
 * pre-IBKR years (which the broker transfer preserved with original dates and cost
 * basis), real deposits from there on. Deposits take over as soon as they exist
 * because lot cost basis cannot survive a rotation — selling one ETF to buy another
 * counts the same money twice.
 *
 * Deployed rides along as a muted suffix: once rotation starts it exceeds money in,
 * and that gap is capital churn rather than saving, so it has to be visible without
 * hovering.
 */
export function ContributionsStrip({ data, isLoading, isError }: ContributionsStripProps) {
  const curSym = useCurrencySymbol()
  const formatCurrency = useFormatCurrency()

  if (isLoading) {
    return <div className="ml-auto h-8 w-80 animate-pulse rounded bg-muted" />
  }

  // Rendering nothing on a failed fetch made the whole strip silently vanish, which is
  // indistinguishable from "this account has no contribution history" — the class of
  // silent failure the rest of the app now refuses.
  if (isError) {
    return (
      <div className="ml-auto flex items-center gap-1.5 pb-0.5 text-xs text-muted-foreground">
        <PiggyBank className="h-3.5 w-3.5" />
        <span>Avg Monthly unavailable — the backend didn't respond</span>
      </div>
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
    <div className="ml-auto flex flex-wrap items-end gap-x-5 gap-y-2">
      <div
        className="flex items-center gap-1.5 pb-0.5 text-xs text-muted-foreground"
        title={labelTitle}
      >
        <PiggyBank className="h-3.5 w-3.5" />
        <span className="font-medium">Avg Monthly</span>
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
          `${formatCurrency(w.avg_money_in_per_month_eur)} per month`,
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
            {/* The delta sits beside the label rather than on its own line: that is what
                keeps this to two lines inside an already-busy card header. */}
            <div className="flex items-center gap-1 text-[11px] leading-tight text-muted-foreground">
              <span>{WINDOW_LABELS[w.label]}</span>
              {w.money_in_method === 'spliced' && (
                <span className="opacity-60" title="part purchases, part deposits">~</span>
              )}
              {delta !== null && (
                <span className={cn('tabular-nums', deltaColor(delta))}>
                  {delta >= 0 ? '+' : ''}{delta.toFixed(0)}%
                </span>
              )}
            </div>
            <div className="text-sm font-semibold leading-tight tabular-nums">
              {curSym}{round(w.avg_money_in_per_month_eur)}
              {w.partial && <span className="text-muted-foreground">*</span>}
              {/* Omitted under the 'deployed' method, where money in IS deployment and
                  the suffix would just repeat the number beside it. */}
              {w.money_in_method !== 'deployed' && (
                <span className="ml-0.5 text-[10px] font-normal text-muted-foreground">
                  /{round(w.avg_deployed_per_month_eur)}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
