import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/**
 * One KPI card, rendered from a description instead of hand-written per instance.
 *
 * There were sixteen copies of this markup across `PortfolioSummaryCards`,
 * `PerformanceMetricsCards`, `RiskMetricsCards` and `DividendKpiCards`, each repeating
 * the same header/value/footnote tree, the same `text-lg font-bold tabular-nums
 * sm:text-2xl`, and its own idea of what an absent value looks like. Making the values
 * responsive was sixteen mechanical edits that should have been one — which is the
 * concrete cost CLAUDE.md's *dominant failure mode* section predicts, and why extracting
 * this was the top item in STATUS.md's *Worth doing next*.
 *
 * The subtler win is `value == null`. Three of the four files agreed that an absent
 * metric must never render as `0`, and then disagreed about how to say so: `RiskMetrics`
 * had an `Absent()` helper rendering an em dash, `PerformanceMetrics` inlined `N/A`
 * twice. Absence is now one code path, so "unknown is not zero" is structural rather
 * than a convention each new card has to remember.
 */
export type KpiTone = 'neutral' | 'positive' | 'negative' | 'warning' | 'muted'

const TONE_CLASS: Record<KpiTone, string> = {
  neutral: '',
  positive: 'text-green-600',
  negative: 'text-red-600',
  warning: 'text-yellow-600',
  muted: 'text-muted-foreground',
}

/**
 * `text-lg` on a phone, `text-2xl` from `sm` up. A 2-up cell has a ~141px interior and a
 * seven-figure currency string renders at ~182px in `text-2xl`, so the small size is
 * load-bearing rather than cosmetic — see STATUS.md's mobile-layout notes.
 */
const VALUE_CLASS = 'text-lg font-bold tabular-nums sm:text-2xl'

/** What an unknown metric looks like. A dash, never a zero. */
export const ABSENT = '—'

export interface KpiCardProps {
  label: ReactNode
  /**
   * `null`/`undefined` renders {@link ABSENT} in the muted tone and ignores `tone`, so a
   * caller cannot accidentally colour a missing number as if it were good or bad news.
   */
  value: ReactNode
  tone?: KpiTone
  icon?: ReactNode
  /** Footnote, wrapped in the standard muted line. */
  sub?: ReactNode
  /** Arbitrary content in place of `sub` — a `DeltaChip`, say, that must keep its own colours. */
  footer?: ReactNode
  /**
   * Full width in a 2-up phone grid, and never shrinks its value to `text-lg`. For the
   * one figure the page is actually about; the rest tile underneath it.
   */
  hero?: boolean
  /** Native tooltip, for a figure that needs a caveat the footnote has no room for. */
  title?: string
  className?: string
}

export function KpiCard({
  label, value, tone = 'neutral', icon, sub, footer, hero, title, className,
}: KpiCardProps) {
  const absent = value == null
  return (
    <Card className={cn(hero && 'col-span-2 lg:col-span-1', className)} title={title}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div
          className={cn(
            hero ? 'text-2xl font-bold tabular-nums' : VALUE_CLASS,
            TONE_CLASS[absent ? 'muted' : tone],
          )}
        >
          {absent ? ABSENT : value}
        </div>
        {footer}
        {sub != null && <p className="text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

/**
 * The loading row. Was copied verbatim four times, each with its own hardcoded count and
 * its own `Loading...` title — so a skeleton row could differ in shape from the row it
 * stands in for, which is the one thing a skeleton must not do.
 */
export function KpiCardSkeleton({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <Card key={i}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Loading...</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-8 bg-muted animate-pulse rounded" />
          </CardContent>
        </Card>
      ))}
    </>
  )
}
