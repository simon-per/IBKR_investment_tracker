import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import type { DividendSecurityRow } from '@/lib/api'
import { useCurrencySymbol, useFormatCurrency } from '@/lib/CurrencyContext'
import { buildChartSeries, duplicatedSymbols, FC, OTHER } from '@/lib/dividendChart'
import { DeltaChip } from './DeltaChip'
import { DividendCalendar } from './DividendCalendar'
import { DividendKpiCards } from './DividendKpiCards'
import { DividendYearComparison } from './DividendYearComparison'
import { useTheme } from './ThemeProvider'
import { cn } from '@/lib/utils'
import { ScrollableTable } from '@/components/ui/ScrollableTable'

/**
 * Categorical palette from the validated reference set, stepped per theme and
 * checked against this app's actual card surfaces (#ffffff / #020817): adjacent
 * pairs pass CVD dE >= 8.4 and normal-vision dE >= 19.3; all dark steps >= 3:1.
 * The ORDER is the colorblind-safety mechanism — stack order must follow it.
 * Symbols beyond the 8 slots fold into a muted "Other", never a ninth hue.
 */
const SERIES_LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
const SERIES_DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']
const OTHER_COLOR = '#898781'

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function monthLabel(month: string, withYear: boolean): string {
  const [y, m] = month.split('-')
  const name = MONTH_NAMES[Number(m) - 1] ?? month
  return withYear ? `${name} ${y.slice(2)}` : name
}

function SourceBadge({ row }: { row: DividendSecurityRow }) {
  if (row.payouts === 0 && row.forecast_payouts > 0) {
    return (
      <span
        className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-800 dark:bg-violet-950/60 dark:text-violet-200"
        title="No payment received in this period yet — projected from the payout cadence"
      >
        Forecast
      </span>
    )
  }
  if (row.source === 'ibkr') {
    return (
      <span
        className="rounded-full bg-teal-100 px-2 py-0.5 text-xs font-medium text-teal-800 dark:bg-teal-950/60 dark:text-teal-200"
        title="Actual figures from IBKR cash transactions"
      >
        IBKR
      </span>
    )
  }
  return (
    <span
      className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-950/60 dark:text-amber-200"
      title={
        row.source === 'mixed'
          ? 'Mix of IBKR actuals and Yahoo Finance estimates'
          : 'Estimated gross from Yahoo Finance — withholding not reflected'
      }
    >
      {row.source === 'mixed' ? 'Mixed' : 'Est.'}
    </span>
  )
}

export function DividendsTab() {
  const currentYear = new Date().getFullYear()
  const [year, setYear] = useState<number | 'all'>(currentYear)
  const [showForecast, setShowForecast] = useState(true)
  const { theme } = useTheme()
  const curSym = useCurrencySymbol()
  const formatCurrency = useFormatCurrency()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['dividends', 'breakdown', year],
    // Forecast is always fetched; the toggle only hides it, so flipping is instant.
    queryFn: () => api.getDividendBreakdown(year === 'all' ? undefined : year),
    staleTime: 30 * 60 * 1000,
  })

  const palette = theme === 'dark' ? SERIES_DARK : SERIES_LIGHT

  // Extracted so it can be unit-tested: this transformation already carried one
  // silent bug (ranking by a key space the data didn't use), and with no browser
  // in the loop a test is the only way to catch the next one.
  const { chartData, stackSymbols } = useMemo(() => buildChartSeries(data), [data])

  const colorOf = (sym: string) =>
    sym === OTHER ? OTHER_COLOR : palette[stackSymbols.indexOf(sym)] ?? OTHER_COLOR

  const formatAxisTick = (v: number) =>
    Math.abs(v) >= 1000 ? `${curSym}${(v / 1000).toFixed(1)}k` : `${curSym}${v}`

  // Growth per month rides on the response rather than being derived here: it is
  // measured over the whole history, which a year-filtered payload doesn't carry.
  const growthByMonth = useMemo(() => {
    const m = new Map<string, { mom: number | null; yoy: number | null }>()
    for (const bar of data?.months ?? []) {
      m.set(bar.month, { mom: bar.mom_pct ?? null, yoy: bar.yoy_pct ?? null })
    }
    return m
  }, [data])

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rows = payload.filter((p: any) => typeof p.value === 'number' && p.value > 0)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const actual = rows.filter((p: any) => !String(p.dataKey).startsWith(FC))
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const forecast = rows.filter((p: any) => String(p.dataKey).startsWith(FC))
    if (!actual.length && !forecast.length) return null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const total = rows.reduce((s: number, p: any) => s + p.value, 0)
    const growth = growthByMonth.get(label)
    return (
      <div className="rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-md">
        <div className="mb-1 font-medium">{monthLabel(label, true)}</div>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        {actual.map((p: any) => (
          <div key={p.dataKey} className="flex items-center justify-between gap-6">
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: p.fill }} />
              {p.dataKey}
            </span>
            <span className="tabular-nums">{formatCurrency(p.value)}</span>
          </div>
        ))}
        {forecast.length > 0 && (
          <div className="mt-1 border-t border-border/50 pt-1 text-xs text-muted-foreground">
            Forecast
          </div>
        )}
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        {forecast.map((p: any) => (
          <div key={p.dataKey} className="flex items-center justify-between gap-6">
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span
                className="h-2 w-2 rounded-sm border border-dashed"
                style={{ borderColor: p.stroke, backgroundColor: 'transparent' }}
              />
              {String(p.dataKey).slice(FC.length)}
            </span>
            <span className="tabular-nums">{formatCurrency(p.value)}</span>
          </div>
        ))}
        <div className="mt-1 flex items-center justify-between gap-6 border-t border-border/50 pt-1 font-medium">
          <span>Total</span>
          <span className="tabular-nums">{formatCurrency(total)}</span>
        </div>
        {/* Only on realized months — a projected month's "change" would be an
            artifact of the forecast's own flat median, and the backend sends null. */}
        {growth && (growth.mom != null || growth.yoy != null) && (
          <div className="mt-1 flex items-center gap-3 border-t border-border/50 pt-1">
            <DeltaChip pct={growth.mom} label="MoM" />
            <DeltaChip pct={growth.yoy} label="YoY" />
          </div>
        )}
      </div>
    )
  }

  const yearOptions = useMemo(() => {
    const ys = data?.years?.length ? [...data.years] : [currentYear]
    return ys.sort((a, b) => b - a)
  }, [data, currentYear])

  const securities = useMemo(() => {
    const rows = data?.securities ?? []
    // Without the forecast the forecast-only rows are pure noise.
    return showForecast ? rows : rows.filter((r) => r.payouts > 0)
  }, [data, showForecast])

  // A ticker listed on two venues is two securities and two rows; only the table
  // needs the venue, and only where it actually disambiguates.
  const duplicated = useMemo(() => duplicatedSymbols(securities), [securities])

  const upcoming = useMemo(
    () => (showForecast ? data?.upcoming ?? [] : []),
    [data, showForecast],
  )

  const hasAnything = (data?.total_net_eur ?? 0) > 0 || (data?.total_forecast_net_eur ?? 0) > 0
  // The growth block is unwindowed, so it stands even when the selected year is
  // empty — which is exactly when knowing the trend is most useful.
  const hasGrowth = (data?.growth?.annual?.length ?? 0) > 0

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>Dividends</CardTitle>
            <CardDescription>
              {data && hasAnything ? (
                <>
                  Received {formatCurrency(data.total_net_eur)} net
                  {showForecast && data.total_forecast_net_eur > 0 && (
                    <> · projected +{formatCurrency(data.total_forecast_net_eur)}</>
                  )}
                  {data.ibkr_from && (
                    <span
                      className="ml-2 text-xs"
                      title={`IBKR actuals from ${data.ibkr_from}; earlier months are Yahoo Finance estimates`}
                    >
                      (IBKR actuals from {data.ibkr_from})
                    </span>
                  )}
                </>
              ) : (
                'Net dividend income by month and stock'
              )}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="dividend-year" className="sr-only">
              Year
            </label>
            <select
              id="dividend-year"
              value={year}
              onChange={(e) => setYear(e.target.value === 'all' ? 'all' : Number(e.target.value))}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm font-medium"
            >
              <option value="all">All time</option>
              {yearOptions.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <button
              onClick={() => setShowForecast((v) => !v)}
              className={cn(
                'inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium transition-colors',
                showForecast
                  ? 'border-transparent bg-primary text-primary-foreground'
                  : 'border-input bg-background hover:bg-accent hover:text-accent-foreground'
              )}
              title="Overlay projected payments inferred from each stock's payout cadence"
              aria-label="Toggle forecast overlay"
              aria-pressed={showForecast}
            >
              Forecast
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {isError ? (
          <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
            Couldn't load dividends — the backend didn't respond. Try again in a moment.
          </div>
        ) : (
          <>
            {(isLoading || hasGrowth) && (
              <DividendKpiCards
                growth={data?.growth}
                ibkrFrom={data?.ibkr_from ?? null}
                isLoading={isLoading}
              />
            )}

            {isLoading ? (
              <div className="h-80 animate-pulse rounded bg-muted" />
            ) : !data || !hasAnything ? (
              <div className="flex h-32 items-center justify-center text-center text-sm text-muted-foreground">
                No dividends recorded {year === 'all' ? 'yet' : `for ${year}`}. They arrive with
                the IBKR sync; estimates for earlier years come from the dividend sync.
              </div>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" vertical={false} />
                    <XAxis
                      dataKey="month"
                      tickFormatter={(m: string) => monthLabel(m, year === 'all')}
                      tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }}
                      tickLine={false}
                      axisLine={{ stroke: 'hsl(var(--border))' }}
                      interval={year === 'all' ? 'preserveStartEnd' : 0}
                    />
                    <YAxis
                      tickFormatter={formatAxisTick}
                      tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }}
                      tickLine={false}
                      axisLine={false}
                      width={60}
                    />
                    <Tooltip content={renderTooltip} cursor={{ fill: 'hsl(var(--muted))', opacity: 0.35 }} />
                    {stackSymbols.map((s, i) => (
                      <Bar
                        key={s}
                        dataKey={s}
                        stackId="d"
                        fill={colorOf(s)}
                        stroke="hsl(var(--card))"
                        strokeWidth={1}
                        isAnimationActive={false}
                        // Only the topmost series gets the rounded cap, or every
                        // segment in the stack would look like its own bar.
                        radius={i === stackSymbols.length - 1 && !showForecast
                          ? [3, 3, 0, 0] : undefined}
                      />
                    ))}
                    {showForecast &&
                      stackSymbols.map((s, i) => (
                        <Bar
                          key={FC + s}
                          dataKey={FC + s}
                          stackId="d"
                          fill={colorOf(s)}
                          fillOpacity={0.4}
                          stroke={colorOf(s)}
                          strokeDasharray="3 2"
                          strokeWidth={1}
                          isAnimationActive={false}
                          radius={i === stackSymbols.length - 1 ? [3, 3, 0, 0] : undefined}
                        />
                      ))}
                  </BarChart>
                </ResponsiveContainer>

                <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
                  {stackSymbols.map((s) => (
                    <span key={s} className="inline-flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: colorOf(s) }} />
                      {s}
                    </span>
                  ))}
                  {showForecast && (data.total_forecast_net_eur ?? 0) > 0 && (
                    <>
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2.5 w-2.5 rounded-sm border border-dashed border-muted-foreground/70" />
                        translucent = forecast
                      </span>
                      {securities.some((r) => r.forecast_basis === 'gross_estimate') && (
                        <span title="Those rows are projected from published gross dividends per share, because nothing has been received from them yet — withholding tax is not deducted">
                          <span className="text-amber-600 dark:text-amber-500">*</span> gross estimate
                        </span>
                      )}
                      {securities.some(
                        (r) => r.forecast_net_eur > 0 && (r.forecast_samples ?? 9) <= 2
                      ) && (
                        <span title="The schedule for those rows was inferred from only one or two past payments, so the cadence is a guess rather than an observed pattern">
                          <span className="text-amber-600 dark:text-amber-500">n=2</span> thin
                          inference
                        </span>
                      )}
                    </>
                  )}
                  {securities.some((r) => r.trailing_yield_partial && r.trailing_yield_pct != null) && (
                    <span title="Those positions were held for less than the full trailing year, so a partial year's income is divided by the full position value and the yield reads low. Not annualized, because that would invent income.">
                      <span className="text-muted-foreground">†</span> partial-year yield
                    </span>
                  )}
                </div>

                {/* Per-year growth beside what is coming: the two questions the
                    monthly chart cannot answer on a quarterly cadence.
                    Two columns only when both halves have something to show —
                    with the forecast off the calendar is empty, and a bare
                    half-width panel beside dead space looks like a load failure. */}
                <div
                  className={cn(
                    'grid gap-6 border-t border-border pt-5',
                    hasGrowth && upcoming.length > 0 && 'lg:grid-cols-2',
                  )}
                >
                  {hasGrowth && (
                    <DividendYearComparison
                      annual={data.growth!.annual}
                      selectedYear={year}
                      onSelectYear={setYear}
                      showForecast={showForecast}
                    />
                  )}
                  <DividendCalendar upcoming={upcoming} colorOf={colorOf} />
                </div>

                <ScrollableTable label="Per-position dividend table" className="border-t border-border pt-5">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-xs text-muted-foreground">
                        <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
                        <th className="px-2 py-1.5 text-left font-medium">Description</th>
                        <th className="px-2 py-1.5 text-left font-medium">Source</th>
                        <th className="px-2 py-1.5 text-right font-medium">Payouts</th>
                        <th className="px-2 py-1.5 text-right font-medium">Net</th>
                        <th className="px-2 py-1.5 text-right font-medium">Share</th>
                        <th className="px-2 py-1.5 text-right font-medium">Forecast</th>
                        <th className="px-2 py-1.5 text-right font-medium">Next</th>
                        <th
                          className="px-2 py-1.5 text-right font-medium"
                          title="Trailing 12-month net over the position's current market value"
                        >
                          Yield
                        </th>
                        <th
                          className="px-2 py-1.5 text-right font-medium"
                          title="Yield on cost: trailing 12-month net over what the position cost — higher than the current yield on a holding that has appreciated"
                        >
                          YoC
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {securities.map((row) => (
                        <tr key={row.security_id} className="border-b border-border/50">
                          <td className="px-2 py-1.5 font-medium">
                            {row.symbol}
                            {duplicated.has(row.symbol) && row.exchange && (
                              <span className="ml-1 text-xs font-normal text-muted-foreground">
                                {row.exchange}
                              </span>
                            )}
                          </td>
                          <td className="max-w-[14rem] truncate px-2 py-1.5 text-muted-foreground" title={row.description}>
                            {row.description}
                          </td>
                          <td className="px-2 py-1.5">
                            <SourceBadge row={row} />
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums">
                            {row.payouts}
                            {showForecast && row.forecast_payouts > 0 && (
                              <span className="text-muted-foreground"> +{row.forecast_payouts}</span>
                            )}
                          </td>
                          <td
                            className="px-2 py-1.5 text-right tabular-nums"
                            title={`Gross ${formatCurrency(row.gross_eur)} · withholding ${formatCurrency(row.withholding_eur)}`}
                          >
                            {formatCurrency(row.net_eur)}
                          </td>
                          <td
                            className="px-2 py-1.5 text-right tabular-nums text-muted-foreground"
                            title="Share of this period's dividend income, including projections"
                          >
                            {row.share_pct != null ? `${row.share_pct.toFixed(1)}%` : '—'}
                          </td>
                          <td
                            className="px-2 py-1.5 text-right tabular-nums text-muted-foreground"
                            title={
                              row.forecast_basis === 'gross_estimate'
                                ? 'Projected from published gross dividends per share — withholding tax is not deducted, so this runs a little high'
                                : row.forecast_basis === 'net'
                                  ? 'Projected from dividends actually received, net of withholding'
                                  : undefined
                            }
                          >
                            {showForecast && row.forecast_net_eur > 0 ? (
                              <>
                                +{formatCurrency(row.forecast_net_eur)}
                                {row.forecast_basis === 'gross_estimate' && (
                                  <span className="ml-0.5 text-amber-600 dark:text-amber-500">*</span>
                                )}
                                {row.forecast_samples != null && row.forecast_samples <= 2 && (
                                  <span
                                    className="ml-0.5 text-amber-600 dark:text-amber-500"
                                    title={
                                      `Inferred from only ${row.forecast_samples} past payment(s)` +
                                      (row.forecast_cadence_days
                                        ? `, ${row.forecast_cadence_days} days apart`
                                        : '') +
                                      ' — treat the schedule as a guess'
                                    }
                                  >
                                    n={row.forecast_samples}
                                  </span>
                                )}
                              </>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                            {showForecast && row.next_pay_date
                              ? monthLabel(row.next_pay_date.slice(0, 7), true)
                              : '—'}
                          </td>
                          <td
                            className="px-2 py-1.5 text-right tabular-nums"
                            title={
                              row.trailing_yield_partial && row.trailing_yield_pct != null
                                ? `Held only ${row.days_held_in_ttm ?? '<365'} of the last 365 days, ` +
                                  `so a partial year's income is divided by the full position ` +
                                  `value — the real yield is higher`
                                : undefined
                            }
                          >
                            {row.trailing_yield_pct != null ? (
                              <>
                                {row.trailing_yield_pct.toFixed(2)}%
                                {row.trailing_yield_partial && (
                                  <span className="ml-0.5 text-muted-foreground">†</span>
                                )}
                              </>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                            {row.yield_on_cost_pct != null ? `${row.yield_on_cost_pct.toFixed(2)}%` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollableTable>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
