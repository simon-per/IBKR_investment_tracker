import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Download, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { useCurrencySymbol } from '@/lib/CurrencyContext'
import type { TaxReport } from '@/lib/api'

const FIRST_TAX_YEAR = 2024

function formatMoney(amount: number): string {
  return amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Green for gains, red for losses, muted for zero. */
function gainClass(amount: number): string {
  if (amount > 0) return 'text-green-600 dark:text-green-400'
  if (amount < 0) return 'text-red-600 dark:text-red-400'
  return 'text-muted-foreground'
}

export function TaxTab() {
  const curSym = useCurrencySymbol()
  const currentYear = new Date().getFullYear()
  const [year, setYear] = useState(currentYear)

  const years: number[] = []
  for (let y = currentYear; y >= FIRST_TAX_YEAR; y--) years.push(y)

  const { data, isLoading, isError, error } = useQuery<TaxReport>({
    queryKey: ['tax', 'report', year],
    queryFn: () => api.getTaxReport(year),
    staleTime: 30 * 60 * 1000, // 30 min
  })

  const money = (n: number) => `${curSym}${formatMoney(n)}`

  return (
    <div className="space-y-6">
      {/* Header: year selector + CSV download */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Tax Report</CardTitle>
              <CardDescription>
                Swiss filing aid — dividend income &amp; foreign withholding (DA-1), realized
                gains, and year-end holdings (wealth tax). Amounts in{' '}
                {data?.base_currency ?? 'base currency'}.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <label htmlFor="tax-year" className="text-sm text-muted-foreground">
                Year
              </label>
              <select
                id="tax-year"
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm font-medium"
              >
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
              <a
                href={api.getTaxReportCsvUrl(year)}
                download={`tax_report_${year}.csv`}
                className={cn(
                  'inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-input bg-background px-3 text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
                )}
              >
                <Download className="h-4 w-4" />
                Download CSV
              </a>
            </div>
          </div>
          {data && (
            <p className="mt-2 text-xs text-muted-foreground">
              Not tax advice — an aid for filing, not an official form.
            </p>
          )}
        </CardHeader>
      </Card>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading tax report…
        </div>
      ) : isError ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-red-600 dark:text-red-400">
            Failed to load tax report: {error instanceof Error ? error.message : 'Unknown error'}
          </CardContent>
        </Card>
      ) : data ? (
        <>
          {/* --- Dividend income + withholding (DA-1) --- */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>Dividend income &amp; withholding (DA-1)</CardTitle>
                  <CardDescription>
                    Taxable dividend income. Foreign withholding tax is reclaimable via the DA-1
                    form.
                  </CardDescription>
                </div>
                <span
                  className={cn(
                    'rounded-full px-2.5 py-1 text-xs font-medium',
                    data.dividend_source === 'ibkr'
                      ? 'bg-teal-100 text-teal-800 dark:bg-teal-950/60 dark:text-teal-200'
                      : data.dividend_source === 'mixed'
                        ? 'bg-sky-100 text-sky-800 dark:bg-sky-950/60 dark:text-sky-200'
                        : 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200'
                  )}
                  title={
                    data.dividend_source === 'ibkr'
                      ? 'Actual figures from IBKR cash transactions'
                      : data.dividend_source === 'mixed'
                        ? `Estimates before ${data.dividend_ibkr_from ?? 'the IBKR era'}; IBKR actuals with real withholding from there on`
                        : 'Estimated gross from Yahoo Finance — withholding not reflected'
                  }
                >
                  {data.dividend_source === 'ibkr'
                    ? 'IBKR actual'
                    : data.dividend_source === 'mixed'
                      ? 'Mixed (est. + IBKR)'
                      : 'Estimated (yfinance)'}
                </span>
              </div>
            </CardHeader>
            <CardContent>
              {data.dividend_income.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No dividend income recorded for {year}.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
                        <th className="px-2 py-1.5 text-left font-medium">Description</th>
                        <th className="px-2 py-1.5 text-left font-medium">Pay date</th>
                        <th className="px-2 py-1.5 text-right font-medium">Gross</th>
                        <th className="px-2 py-1.5 text-right font-medium">Withholding</th>
                        <th className="px-2 py-1.5 text-right font-medium">Net</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.dividend_income.map((d, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="px-2 py-1.5 font-medium">{d.symbol ?? '—'}</td>
                          <td className="max-w-[240px] truncate px-2 py-1.5 text-muted-foreground" title={d.description ?? ''}>
                            {d.description ?? '—'}
                          </td>
                          <td className="px-2 py-1.5">{d.pay_date}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{money(d.gross)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                            {d.withholding ? `-${money(d.withholding)}` : money(0)}
                          </td>
                          <td className="px-2 py-1.5 text-right font-medium tabular-nums">{money(d.net)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t font-semibold">
                        <td className="px-2 py-2" colSpan={3}>
                          Total
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{money(data.dividend_totals.gross)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">
                          {data.dividend_totals.withholding ? `-${money(data.dividend_totals.withholding)}` : money(0)}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{money(data.dividend_totals.net)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* --- Withholding by country (DA-1 is filed per source country) --- */}
          {data.dividend_by_country.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Withholding by country (DA-1)</CardTitle>
                <CardDescription>{data.dividend_country_note}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="px-2 py-1.5 text-left font-medium">Country</th>
                        <th className="px-2 py-1.5 text-right font-medium">Positions</th>
                        <th className="px-2 py-1.5 text-right font-medium">Gross</th>
                        <th className="px-2 py-1.5 text-right font-medium">Withholding</th>
                        <th className="px-2 py-1.5 text-right font-medium">Net</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.dividend_by_country.map((c) => (
                        <tr key={c.country} className="border-b border-border/50">
                          <td className="px-2 py-1.5 font-medium">{c.country}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                            {c.positions}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{money(c.gross)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">
                            {c.withholding ? `-${money(c.withholding)}` : money(0)}
                          </td>
                          <td className="px-2 py-1.5 text-right font-medium tabular-nums">{money(c.net)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* --- Realized capital gains --- */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>Realized capital gains</CardTitle>
                  <CardDescription>
                    Switzerland does not tax private capital gains — shown for completeness and
                    other regimes.
                  </CardDescription>
                </div>
                <span
                  className={cn(
                    'rounded-full px-2.5 py-1 text-xs font-medium',
                    data.realized_source === 'trades'
                      ? 'bg-teal-100 text-teal-800 dark:bg-teal-950/60 dark:text-teal-200'
                      : 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200'
                  )}
                  title={
                    data.realized_source === 'trades'
                      ? "Exact figures from IBKR trade executions (FIFO realized P&L)"
                      : 'Estimated from closed lots at market price on the close date — no IBKR trade data for this year'
                  }
                >
                  {data.realized_source === 'trades' ? 'IBKR actual' : 'Estimated (closed lots)'}
                </span>
              </div>
            </CardHeader>
            <CardContent>
              {data.realized_gains.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No realized sales recorded for {year}.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
                        <th className="px-2 py-1.5 text-left font-medium">Trade date</th>
                        <th className="px-2 py-1.5 text-right font-medium">Quantity</th>
                        <th className="px-2 py-1.5 text-right font-medium">Proceeds</th>
                        <th className="px-2 py-1.5 text-right font-medium">Cost basis</th>
                        <th className="px-2 py-1.5 text-right font-medium">Gain / Loss</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.realized_gains.map((r, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="px-2 py-1.5 font-medium">{r.symbol ?? '—'}</td>
                          <td className="px-2 py-1.5">{r.trade_date}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">
                            {r.quantity != null ? r.quantity : '—'}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{money(r.proceeds)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{money(r.cost_basis)}</td>
                          <td className={cn('px-2 py-1.5 text-right font-medium tabular-nums', gainClass(r.gain_loss))}>
                            {r.gain_loss >= 0 ? '+' : ''}
                            {money(r.gain_loss)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t font-semibold">
                        <td className="px-2 py-2" colSpan={3}>
                          Total
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{money(data.realized_totals.proceeds)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{money(data.realized_totals.cost_basis)}</td>
                        <td className={cn('px-2 py-2 text-right tabular-nums', gainClass(data.realized_totals.gain_loss))}>
                          {data.realized_totals.gain_loss >= 0 ? '+' : ''}
                          {money(data.realized_totals.gain_loss)}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* --- Holdings snapshot (wealth tax) --- */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>Holdings snapshot (wealth tax / Steuerwert)</CardTitle>
                  <CardDescription>{data.holdings_snapshot_note}</CardDescription>
                </div>
                <span
                  className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground"
                  title="Swiss wealth tax is assessed on the 31 December value"
                >
                  as at {data.holdings_as_of}
                </span>
              </div>
            </CardHeader>
            <CardContent>
              {data.holdings_snapshot.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">No holdings to show.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
                        <th className="px-2 py-1.5 text-right font-medium">Quantity</th>
                        <th className="px-2 py-1.5 text-right font-medium">Market value</th>
                        <th className="px-2 py-1.5 text-right font-medium">Cost basis</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.holdings_snapshot.map((h, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="px-2 py-1.5 font-medium">{h.symbol ?? '—'}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">
                            {h.quantity != null ? h.quantity : '—'}
                          </td>
                          <td className="px-2 py-1.5 text-right font-medium tabular-nums">{money(h.market_value)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{money(h.cost_basis)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t font-semibold">
                        <td className="px-2 py-2" colSpan={2}>
                          Total
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{money(data.holdings_snapshot_total)}</td>
                        <td className="px-2 py-2" />
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  )
}
