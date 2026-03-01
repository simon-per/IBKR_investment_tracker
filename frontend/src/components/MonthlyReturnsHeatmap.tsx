import { useState, useMemo } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PortfolioValuePoint } from '@/lib/api'

interface MonthlyReturnsHeatmapProps {
  data: PortfolioValuePoint[] | undefined
  isLoading: boolean
}

interface MonthReturn {
  returnPercent: number
  startValue: number
  endValue: number
}

interface YearRow {
  year: number
  months: (MonthReturn | null)[]
  ytd: MonthReturn | null
}

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function getReturnColor(pct: number): string {
  // Clamp to [-10, 10] for color scaling
  const clamped = Math.max(-10, Math.min(10, pct))
  const intensity = Math.abs(clamped) / 10

  if (pct >= 0) {
    // Green scale - light to dark
    if (intensity < 0.2) return 'bg-green-100 dark:bg-green-950/40 text-green-800 dark:text-green-200'
    if (intensity < 0.4) return 'bg-green-200 dark:bg-green-900/60 text-green-900 dark:text-green-100'
    if (intensity < 0.6) return 'bg-green-300 dark:bg-green-800/70 text-green-900 dark:text-green-100'
    if (intensity < 0.8) return 'bg-green-400 dark:bg-green-700/80 text-white dark:text-green-50'
    return 'bg-green-500 dark:bg-green-600 text-white'
  } else {
    // Red scale - light to dark
    if (intensity < 0.2) return 'bg-red-100 dark:bg-red-950/40 text-red-800 dark:text-red-200'
    if (intensity < 0.4) return 'bg-red-200 dark:bg-red-900/60 text-red-900 dark:text-red-100'
    if (intensity < 0.6) return 'bg-red-300 dark:bg-red-800/70 text-red-900 dark:text-red-100'
    if (intensity < 0.8) return 'bg-red-400 dark:bg-red-700/80 text-white dark:text-red-50'
    return 'bg-red-500 dark:bg-red-600 text-white'
  }
}

export function MonthlyReturnsHeatmap({ data, isLoading }: MonthlyReturnsHeatmapProps) {
  const [open, setOpen] = useState(false)

  const yearRows = useMemo(() => {
    if (!data || data.length < 2) return []

    // Group data points by YYYY-MM
    const monthGroups = new Map<string, PortfolioValuePoint[]>()
    for (const point of data) {
      const key = point.date.substring(0, 7) // "YYYY-MM"
      const group = monthGroups.get(key)
      if (group) {
        group.push(point)
      } else {
        monthGroups.set(key, [point])
      }
    }

    // Compute return per month
    const monthReturns = new Map<string, MonthReturn>()
    for (const [key, points] of monthGroups) {
      if (points.length < 2) continue
      const first = points[0].market_value_eur
      const last = points[points.length - 1].market_value_eur
      if (first === 0) continue
      monthReturns.set(key, {
        returnPercent: ((last - first) / first) * 100,
        startValue: first,
        endValue: last,
      })
    }

    // Organize into year rows
    const yearMap = new Map<number, (MonthReturn | null)[]>()
    for (const [key] of monthReturns) {
      const year = parseInt(key.substring(0, 4))
      if (!yearMap.has(year)) {
        yearMap.set(year, new Array(12).fill(null))
      }
      const monthIndex = parseInt(key.substring(5, 7)) - 1
      yearMap.get(year)![monthIndex] = monthReturns.get(key)!
    }

    // Compute YTD for each year
    const rows: YearRow[] = []
    for (const [year, months] of yearMap) {
      // Find first and last data points for this year
      const yearPrefix = String(year)
      let ytdStart: number | null = null
      let ytdEnd: number | null = null

      for (const point of data) {
        if (point.date.startsWith(yearPrefix)) {
          if (ytdStart === null) ytdStart = point.market_value_eur
          ytdEnd = point.market_value_eur
        }
      }

      let ytd: MonthReturn | null = null
      if (ytdStart !== null && ytdEnd !== null && ytdStart > 0) {
        ytd = {
          returnPercent: ((ytdEnd - ytdStart) / ytdStart) * 100,
          startValue: ytdStart,
          endValue: ytdEnd,
        }
      }

      rows.push({ year, months, ytd })
    }

    // Sort descending (most recent on top)
    rows.sort((a, b) => b.year - a.year)
    return rows
  }, [data])

  // Summary text for collapsed state
  let summaryText: React.ReactNode = 'Monthly return percentages by year'
  if (yearRows.length > 0) {
    const topRow = yearRows[0]
    // Find last filled month
    let lastMonthIdx = -1
    for (let i = 11; i >= 0; i--) {
      if (topRow.months[i] !== null) {
        lastMonthIdx = i
        break
      }
    }
    const parts: React.ReactNode[] = []
    if (lastMonthIdx >= 0) {
      const m = topRow.months[lastMonthIdx]!
      parts.push(
        <span key="month">
          {MONTH_LABELS[lastMonthIdx]}:{' '}
          <span className={m.returnPercent >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
            {m.returnPercent >= 0 ? '+' : ''}{m.returnPercent.toFixed(1)}%
          </span>
        </span>
      )
    }
    if (topRow.ytd) {
      parts.push(
        <span key="ytd">
          {' · '}YTD:{' '}
          <span className={topRow.ytd.returnPercent >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
            {topRow.ytd.returnPercent >= 0 ? '+' : ''}{topRow.ytd.returnPercent.toFixed(1)}%
          </span>
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
            <CardTitle>Monthly Returns</CardTitle>
            <CardDescription>{summaryText}</CardDescription>
          </div>
        </div>
      </CardHeader>
      {open && (
        <CardContent>
          {isLoading ? (
            <div className="h-[200px] w-full animate-pulse rounded-md bg-muted" />
          ) : yearRows.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">
              Not enough data to compute monthly returns.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th className="text-left font-medium text-muted-foreground px-2 py-1.5">Year</th>
                    {MONTH_LABELS.map(m => (
                      <th key={m} className="text-center font-medium text-muted-foreground px-1 py-1.5 min-w-[52px]">{m}</th>
                    ))}
                    <th className="text-center font-medium text-muted-foreground px-2 py-1.5 min-w-[60px] border-l">YTD</th>
                  </tr>
                </thead>
                <tbody>
                  {yearRows.map(row => (
                    <tr key={row.year}>
                      <td className="font-medium px-2 py-1">{row.year}</td>
                      {row.months.map((m, i) => (
                        <td key={i} className="px-0.5 py-0.5">
                          {m ? (
                            <div
                              className={cn(
                                'rounded px-1.5 py-1 text-center text-xs font-medium',
                                getReturnColor(m.returnPercent)
                              )}
                              title={`${MONTH_LABELS[i]} ${row.year}: ${m.returnPercent >= 0 ? '+' : ''}${m.returnPercent.toFixed(2)}% (€${m.startValue.toLocaleString('en-US', { maximumFractionDigits: 0 })} → €${m.endValue.toLocaleString('en-US', { maximumFractionDigits: 0 })})`}
                            >
                              {m.returnPercent >= 0 ? '+' : ''}{m.returnPercent.toFixed(1)}%
                            </div>
                          ) : (
                            <div className="text-center text-xs text-muted-foreground py-1">–</div>
                          )}
                        </td>
                      ))}
                      <td className="px-0.5 py-0.5 border-l">
                        {row.ytd ? (
                          <div
                            className={cn(
                              'rounded px-1.5 py-1 text-center text-xs font-medium',
                              getReturnColor(row.ytd.returnPercent)
                            )}
                            title={`YTD ${row.year}: ${row.ytd.returnPercent >= 0 ? '+' : ''}${row.ytd.returnPercent.toFixed(2)}% (€${row.ytd.startValue.toLocaleString('en-US', { maximumFractionDigits: 0 })} → €${row.ytd.endValue.toLocaleString('en-US', { maximumFractionDigits: 0 })})`}
                          >
                            {row.ytd.returnPercent >= 0 ? '+' : ''}{row.ytd.returnPercent.toFixed(1)}%
                          </div>
                        ) : (
                          <div className="text-center text-xs text-muted-foreground py-1">–</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}
