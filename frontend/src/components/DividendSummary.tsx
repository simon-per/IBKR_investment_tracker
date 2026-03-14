import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ChevronRight, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import type { DividendSummaryResponse } from '@/lib/api'

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

interface YearRow {
  year: number
  months: (number | null)[]
  yearTotal: number
}

function getAmountColor(amount: number, maxAmount: number): string {
  if (amount <= 0) return ''
  const intensity = maxAmount > 0 ? Math.min(amount / maxAmount, 1) : 0

  if (intensity < 0.2) return 'bg-teal-100 dark:bg-teal-950/40 text-teal-800 dark:text-teal-200'
  if (intensity < 0.4) return 'bg-teal-200 dark:bg-teal-900/60 text-teal-900 dark:text-teal-100'
  if (intensity < 0.6) return 'bg-teal-300 dark:bg-teal-800/70 text-teal-900 dark:text-teal-100'
  if (intensity < 0.8) return 'bg-teal-400 dark:bg-teal-700/80 text-white dark:text-teal-50'
  return 'bg-teal-500 dark:bg-teal-600 text-white'
}

function formatEur(amount: number): string {
  return amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function DividendSummary() {
  const [open, setOpen] = useState(false)

  const { data, isLoading } = useQuery<DividendSummaryResponse>({
    queryKey: ['dividends', 'summary'],
    queryFn: () => api.getDividendSummary(),
    staleTime: 30 * 60 * 1000, // 30 min
    refetchInterval: (query) => {
      // Poll every 30s while sync is in progress
      return query.state.data?.sync_in_progress ? 30_000 : false
    },
  })

  const { yearRows, maxMonthlyAmount } = useMemo(() => {
    if (!data?.monthly?.length) return { yearRows: [], maxMonthlyAmount: 0 }

    // Build year → month grid
    const yearMap = new Map<number, (number | null)[]>()
    let maxAmt = 0

    for (const item of data.monthly) {
      const year = parseInt(item.month.substring(0, 4))
      const monthIdx = parseInt(item.month.substring(5, 7)) - 1

      if (!yearMap.has(year)) {
        yearMap.set(year, new Array(12).fill(null))
      }
      yearMap.get(year)![monthIdx] = item.amount_eur
      if (item.amount_eur > maxAmt) maxAmt = item.amount_eur
    }

    const rows: YearRow[] = []
    for (const [year, months] of yearMap) {
      const yearTotal = months.reduce<number>((sum, v) => sum + (v ?? 0), 0)
      rows.push({ year, months, yearTotal })
    }

    rows.sort((a, b) => b.year - a.year)
    // Filter out years with no dividend income
    const filtered = rows.filter(r => r.yearTotal > 0)
    return { yearRows: filtered, maxMonthlyAmount: maxAmt }
  }, [data])

  // Summary text for collapsed state
  let summaryText: React.ReactNode = 'Gross dividend income by month'
  if (data) {
    const parts: React.ReactNode[] = []
    if (data.ytd_eur > 0) {
      parts.push(
        <span key="ytd">
          YTD: <span className="text-teal-600 dark:text-teal-400">{'\u20AC'}{formatEur(data.ytd_eur)}</span>
        </span>
      )
    }
    if (data.total_eur > 0) {
      parts.push(
        <span key="total">
          {parts.length > 0 ? ' \u00B7 ' : ''}Total: <span className="text-teal-600 dark:text-teal-400">{'\u20AC'}{formatEur(data.total_eur)}</span>
        </span>
      )
    }
    if (data.sync_in_progress) {
      parts.push(
        <span key="sync" className="inline-flex items-center gap-1 text-muted-foreground">
          {parts.length > 0 ? ' \u00B7 ' : ''}<Loader2 className="h-3 w-3 animate-spin" /> Syncing...
        </span>
      )
    }
    if (parts.length > 0) summaryText = <>{parts}</>
  }

  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2">
          <ChevronRight className={cn('h-5 w-5 text-muted-foreground transition-transform duration-200', open && 'rotate-90')} />
          <div>
            <CardTitle>Dividend Income</CardTitle>
            <CardDescription>{summaryText}</CardDescription>
          </div>
        </div>
      </CardHeader>
      {open && (
        <CardContent>
          {isLoading ? (
            <div className="h-[200px] w-full animate-pulse rounded-md bg-muted" />
          ) : yearRows.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-muted-foreground">
                {data?.sync_in_progress
                  ? 'Syncing dividend data... This may take a few minutes.'
                  : 'No dividend data available yet.'}
              </p>
              {data?.sync_in_progress && <Loader2 className="h-5 w-5 animate-spin mx-auto mt-2 text-muted-foreground" />}
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className="text-left font-medium text-muted-foreground px-2 py-1.5">Year</th>
                      {MONTH_LABELS.map(m => (
                        <th key={m} className="text-center font-medium text-muted-foreground px-1 py-1.5 min-w-[52px]">{m}</th>
                      ))}
                      <th className="text-center font-medium text-muted-foreground px-2 py-1.5 min-w-[70px] border-l">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {yearRows.map(row => (
                      <tr key={row.year}>
                        <td className="font-medium px-2 py-1">{row.year}</td>
                        {row.months.map((amount, i) => (
                          <td key={i} className="px-0.5 py-0.5">
                            {amount !== null && amount > 0 ? (
                              <div
                                className={cn(
                                  'rounded px-1.5 py-1 text-center text-xs font-medium',
                                  getAmountColor(amount, maxMonthlyAmount)
                                )}
                                title={`${MONTH_LABELS[i]} ${row.year}: \u20AC${formatEur(amount)}`}
                              >
                                {'\u20AC'}{amount < 10 ? amount.toFixed(2) : amount.toFixed(0)}
                              </div>
                            ) : (
                              <div className="text-center text-xs text-muted-foreground py-1">{'\u2013'}</div>
                            )}
                          </td>
                        ))}
                        <td className="px-0.5 py-0.5 border-l">
                          {row.yearTotal > 0 ? (
                            <div
                              className={cn(
                                'rounded px-1.5 py-1 text-center text-xs font-medium',
                                getAmountColor(row.yearTotal, maxMonthlyAmount)
                              )}
                              title={`Total ${row.year}: \u20AC${formatEur(row.yearTotal)}`}
                            >
                              {'\u20AC'}{formatEur(row.yearTotal)}
                            </div>
                          ) : (
                            <div className="text-center text-xs text-muted-foreground py-1">{'\u2013'}</div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground mt-3 italic">
                Estimated gross dividends via Yahoo Finance — withholding taxes, ADR fees, and minor FX differences not reflected
              </p>
            </>
          )}
        </CardContent>
      )}
    </Card>
  )
}
