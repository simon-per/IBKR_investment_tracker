import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ScrollableTable } from '@/components/ui/ScrollableTable'
import { Download, ArrowLeftRight, Banknote, Coins, Split } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { useCurrencySymbol } from '@/lib/CurrencyContext'
import { rangeFor, type TimeRange } from '@/lib/dateRanges'
import type { ActivityKind, ActivityRow } from '@/lib/api'

const PAGE_SIZE = 100

/** The ranges that make sense for a ledger: a fixed window, not a chart's zoom. */
const RANGES: TimeRange[] = ['1M', '3M', '6M', 'YTD', '1Y', '2Y', 'ALL']

const KIND_LABELS: Record<ActivityKind, string> = {
  trade: 'Trades',
  dividend: 'Dividends',
  cash_flow: 'Cash',
  corporate_action: 'Corporate actions',
}

const KIND_ICONS: Record<ActivityKind, typeof Coins> = {
  trade: ArrowLeftRight,
  dividend: Coins,
  cash_flow: Banknote,
  corporate_action: Split,
}

const ALL_KINDS = Object.keys(KIND_LABELS) as ActivityKind[]

function signClass(amount: number | null | undefined): string {
  if (amount == null || amount === 0) return 'text-muted-foreground'
  return amount > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
}

function num(value: number | null, digits = 2): string {
  if (value == null) return '—'
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/**
 * A share count, with as much precision as it actually carries and no more.
 *
 * Rounding to whole shares turned this account's fractional trades into `0` and, worse,
 * `-0` — 0.3 MU and 0.1 CSU are ordinary rows here, not edge cases. Six decimals is the
 * column's own precision (`Numeric(18, 6)`); `maximumFractionDigits` alone trims the
 * trailing zeros, so a whole-share trade still reads `50` rather than `50.000000`.
 */
function qty(value: number | null): string {
  if (value == null) return '—'
  // Intl renders -0.0000001 as "-0"; the sign is already in the BUY/SELL badge.
  const shown = Object.is(value, -0) ? 0 : value
  return shown.toLocaleString('en-US', { maximumFractionDigits: 6 })
}

/**
 * What a row's subtype badge should say, and how loudly.
 *
 * The transfer case is the one that earns its colour: an incoming transfer booked as
 * an ordinary deposit shows up as a portfolio-sized fake contribution, and until this
 * tab existed the only way to eyeball those rows was `manage_cash_flows list` over ssh.
 */
function subtypeBadge(row: ActivityRow): { text: string; className: string } {
  if (row.kind === 'cash_flow') {
    if (row.counts_as_money_in) {
      return {
        text: (row.amount_base ?? 0) < 0 ? 'Withdrawal' : 'Deposit',
        className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200',
      }
    }
    return {
      text: 'Transfer · not money in',
      className: 'bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200',
    }
  }
  if (row.kind === 'trade') {
    const isSell = row.subtype.toUpperCase().includes('SELL')
    return {
      text: row.subtype || 'Trade',
      className: isSell
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
    }
  }
  if (row.kind === 'dividend') {
    // Estimates are a gross guess with no withholding — the same honesty flag the tax
    // report and the dividend card carry.
    const estimated = row.source === 'yfinance_estimate'
    return {
      text: estimated ? 'Dividend · est.' : 'Dividend',
      className: estimated
        ? 'bg-muted text-muted-foreground'
        : 'bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-200',
    }
  }
  return { text: row.subtype || 'Action', className: 'bg-muted text-muted-foreground' }
}

/**
 * The account's transaction ledger.
 *
 * `trades`, `corporate_actions`, `cash_flows` and `dividend_payments` were all ingested,
 * reconciled and depended on — the tax report reads trades, the contributions splice
 * reads cash flows — while none of them had any read surface at all.
 */
export function ActivityTab() {
  const curSym = useCurrencySymbol()
  const [range, setRange] = useState<TimeRange>('1Y')
  const [kinds, setKinds] = useState<ActivityKind[]>([])
  const [symbol, setSymbol] = useState('')
  const [symbolDraft, setSymbolDraft] = useState('')
  const [page, setPage] = useState(0)

  // Shares Dashboard's inception source so ALL starts at the first tax lot rather than
  // a hardcoded date — transferred lots keep their original open_date.
  const { data: contributions } = useQuery({
    queryKey: ['portfolio', 'contributions'],
    queryFn: () => api.getContributions(),
    staleTime: 30 * 60 * 1000,
  })

  const window = useMemo(
    () => rangeFor(range, new Date(), contributions?.first_contribution_date ?? null),
    [range, contributions]
  )

  const params = useMemo(
    () => ({
      startDate: window.start,
      endDate: window.end,
      kinds: kinds.length ? kinds : undefined,
      symbol: symbol || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [window, kinds, symbol, page]
  )

  const { data, isLoading, isError } = useQuery({
    queryKey: ['portfolio', 'activity', params],
    queryFn: () => api.getActivity(params),
    staleTime: 5 * 60 * 1000,
  })

  /** Any filter change invalidates the page number — page 4 of a narrower result is
      usually empty, which reads as "no activity" rather than "you moved the goalposts". */
  const withReset = <T,>(setter: (v: T) => void) => (value: T) => {
    setter(value)
    setPage(0)
  }

  const toggleKind = withReset((kind: ActivityKind) =>
    setKinds(current =>
      current.includes(kind) ? current.filter(k => k !== kind) : [...current, kind]
    )
  )

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>Activity</CardTitle>
              <CardDescription>
                Every trade, dividend, deposit and corporate action, newest first
                {data ? ` · ${data.total.toLocaleString('en-US')} events` : ''}
              </CardDescription>
            </div>
            <a
              href={api.getActivityCsvUrl({ ...params, limit: undefined, offset: undefined })}
              className="inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-input bg-background px-3 text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <Download className="h-4 w-4" />
              Download CSV
            </a>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3">
            <div className="flex flex-wrap gap-1" role="group" aria-label="Time range">
              {RANGES.map(r => (
                <Button
                  key={r}
                  size="sm"
                  variant={range === r ? 'default' : 'outline'}
                  aria-pressed={range === r}
                  onClick={() => withReset(setRange)(r)}
                >
                  {r}
                </Button>
              ))}
            </div>

            <div className="flex flex-wrap gap-1" role="group" aria-label="Event types">
              {ALL_KINDS.map(kind => {
                const Icon = KIND_ICONS[kind]
                // Empty selection means everything, so nothing is highlighted and no
                // combination of clicks can produce an empty table by accident.
                const active = kinds.includes(kind)
                return (
                  <Button
                    key={kind}
                    size="sm"
                    variant={active ? 'default' : 'outline'}
                    aria-pressed={active}
                    onClick={() => toggleKind(kind)}
                  >
                    <Icon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                    {KIND_LABELS[kind]}
                  </Button>
                )
              })}
            </div>

            <form
              onSubmit={e => {
                e.preventDefault()
                withReset(setSymbol)(symbolDraft.trim().toUpperCase())
              }}
              className="flex items-center gap-2"
            >
              <label htmlFor="activity-symbol" className="sr-only">
                Filter by ticker
              </label>
              <input
                id="activity-symbol"
                value={symbolDraft}
                onChange={e => setSymbolDraft(e.target.value)}
                placeholder="Ticker"
                className="h-9 w-28 rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
              <Button type="submit" size="sm" variant="outline">
                Filter
              </Button>
              {symbol && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setSymbolDraft('')
                    withReset(setSymbol)('')
                  }}
                >
                  Clear
                </Button>
              )}
            </form>
          </div>
        </CardHeader>

        <CardContent>
          {isLoading ? (
            <div className="h-[400px] w-full animate-pulse rounded-md bg-muted" />
          ) : isError ? (
            // Never let a backend failure read as "nothing happened in this window".
            <p className="py-12 text-center text-muted-foreground">
              Couldn't load activity — the backend didn't respond. It retries automatically.
            </p>
          ) : !data || data.items.length === 0 ? (
            <p className="py-12 text-center text-muted-foreground">
              No activity in this window.
              {(kinds.length > 0 || symbol) && ' Try widening the filters.'}
            </p>
          ) : (
            <>
              <ScrollableTable label="Activity table">
                <table className="w-full text-sm">
                  <caption className="sr-only">
                    Account activity from {data.start_date} to {data.end_date}, newest first
                  </caption>
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th scope="col" className="py-2 pr-3 font-medium">Date</th>
                      <th scope="col" className="py-2 pr-3 font-medium">Type</th>
                      <th scope="col" className="py-2 pr-3 font-medium">Symbol</th>
                      <th scope="col" className="py-2 pr-3 font-medium">Detail</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Quantity</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">Price</th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">
                        Amount ({data.base_currency})
                      </th>
                      <th scope="col" className="py-2 text-right font-medium">Realized</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map(row => {
                      const badge = subtypeBadge(row)
                      return (
                        <tr key={row.ib_key ?? `${row.kind}-${row.date}`} className="border-b last:border-0">
                          <td className="whitespace-nowrap py-2 pr-3 tabular-nums">{row.date}</td>
                          <td className="py-2 pr-3">
                            <span className={cn('whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium', badge.className)}>
                              {badge.text}
                            </span>
                          </td>
                          <td className="py-2 pr-3 font-medium">{row.symbol ?? '—'}</td>
                          <td className="max-w-[22rem] truncate py-2 pr-3 text-muted-foreground" title={row.description}>
                            {row.description}
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums">
                            {qty(row.quantity)}
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums">
                            {row.price == null ? '—' : `${num(row.price)} ${row.currency ?? ''}`.trim()}
                          </td>
                          <td className={cn('py-2 pr-3 text-right font-medium tabular-nums', signClass(row.amount_base))}>
                            {row.amount_base == null ? '—' : `${curSym}${num(row.amount_base)}`}
                          </td>
                          <td className={cn('py-2 text-right tabular-nums', signClass(row.realized_pnl_base))}>
                            {row.realized_pnl_base == null ? '—' : `${curSym}${num(row.realized_pnl_base)}`}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </ScrollableTable>

              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
                  <span>
                    {data.offset + 1}–{Math.min(data.offset + data.limit, data.total)} of{' '}
                    {data.total.toLocaleString('en-US')}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages - 1}
                      onClick={() => setPage(p => p + 1)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}

              <p className="mt-4 text-xs text-muted-foreground">
                Amounts are in {data.base_currency}, each converted at its own date. Broker
                transfers are shown but never counted as money added — the capital was
                saved elsewhere and the transferred lots already carry their original
                purchase dates.
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
