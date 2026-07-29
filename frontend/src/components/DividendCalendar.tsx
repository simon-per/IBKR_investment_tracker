import { useMemo } from 'react'
import { useFormatCurrency } from '@/lib/CurrencyContext'
import type { DividendUpcomingPayment } from '@/lib/api'

interface DividendCalendarProps {
  upcoming: DividendUpcomingPayment[]
  /** Colour per stack symbol, shared with the chart so the two agree. */
  colorOf: (symbol: string) => string
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function dayLabel(iso: string): string {
  const [, m, d] = iso.split('-')
  return `${Number(d)} ${MONTH_NAMES[Number(m) - 1] ?? m}`
}

function monthHeading(iso: string): string {
  const [y, m] = iso.split('-')
  return `${MONTH_NAMES[Number(m) - 1] ?? m} ${y}`
}

/**
 * The next projected payments, dated and grouped by month.
 *
 * The projection has always produced dated payments; the chart aggregated them
 * into month buckets and discarded the days, so this costs nothing new. Every
 * amount here is inferred from the holding's own cadence — no dividend calendar
 * is published to any source this app reads — so the heading says so once rather
 * than badging each row.
 */
export function DividendCalendar({ upcoming, colorOf }: DividendCalendarProps) {
  const groups = useMemo(() => {
    const byMonth = new Map<string, DividendUpcomingPayment[]>()
    for (const p of upcoming) {
      const key = p.date.slice(0, 7)
      const list = byMonth.get(key)
      if (list) list.push(p)
      else byMonth.set(key, [p])
    }
    return [...byMonth.entries()]
  }, [upcoming])

  if (upcoming.length === 0) return null

  const anyEstimate = upcoming.some(p => p.basis === 'gross_estimate')

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-medium">Expected next</span>
        <span className="text-xs text-muted-foreground">
          projected from each holding&apos;s payout cadence — not an announced schedule
        </span>
      </div>

      {/* Bounded height: 12 months of a 20-payer portfolio is ~60 rows, which
          would otherwise push the position table off the page. */}
      <div className="max-h-64 space-y-3 overflow-y-auto pr-1">
        {groups.map(([month, rows]) => {
          const monthTotal = rows.reduce((s, r) => s + r.net_eur, 0)
          return (
            <div key={month}>
              <div className="mb-1 flex items-baseline justify-between border-b border-border/60 pb-0.5">
                <span className="text-xs font-medium text-muted-foreground">
                  {monthHeading(month)}
                </span>
                <MonthTotal total={monthTotal} />
              </div>
              <ul className="space-y-0.5">
                {rows.map(p => (
                  <li
                    key={`${p.date}-${p.security_id}`}
                    className="flex items-center gap-2 text-sm"
                  >
                    <span className="w-14 shrink-0 tabular-nums text-xs text-muted-foreground">
                      {dayLabel(p.date)}
                    </span>
                    <span
                      className="h-2 w-2 shrink-0 rounded-sm"
                      style={{ backgroundColor: colorOf(p.symbol) }}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate">{p.symbol}</span>
                    <Amount value={p.net_eur} estimate={p.basis === 'gross_estimate'} />
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>

      {anyEstimate && (
        <div className="text-xs text-muted-foreground">
          <span className="text-amber-600 dark:text-amber-500">*</span>{' '}
          sized from published gross dividends per share, because nothing has been
          received from that holding yet — withholding tax is not deducted, so those
          run a little high
        </div>
      )}
    </div>
  )
}

function MonthTotal({ total }: { total: number }) {
  const formatCurrency = useFormatCurrency()
  return (
    <span className="text-xs tabular-nums text-muted-foreground">
      {formatCurrency(total)}
    </span>
  )
}

function Amount({ value, estimate }: { value: number; estimate: boolean }) {
  const formatCurrency = useFormatCurrency()
  return (
    <span className="shrink-0 tabular-nums">
      {formatCurrency(value)}
      {estimate && (
        <span
          className="ml-0.5 text-amber-600 dark:text-amber-500"
          title="Gross estimate — withholding not deducted"
        >
          *
        </span>
      )}
    </span>
  )
}
