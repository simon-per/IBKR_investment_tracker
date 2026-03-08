import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { WatchlistItem } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { RefreshCw, Plus, Trash2, ArrowDown, ArrowUp } from 'lucide-react'


type SortColumn =
  | 'symbol'
  | 'buy_score'
  | 'current_price'
  | 'pct_from_52w_high'
  | 'rsi14'
  | 'pct_from_ma200'
  | 'trailing_pe'
  | 'forward_pe'
  | 'peg_ratio'
  | 'ev_to_ebitda'
  | 'analyst_rating'
  | 'revenue_growth'
  | 'earnings_growth'
  | 'fwd_revenue_growth'
  | 'fwd_eps_growth'
  | 'profit_margins'
type SortDirection = 'asc' | 'desc'

function formatCurrency(value: number | null, currency: string | null): string {
  if (value === null) return '-'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency || 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatPercent(value: number | null): string {
  if (value === null) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

function formatMarketCap(value: number | null): string {
  if (value === null) return '-'
  if (value >= 1e12) return `${(value / 1e12).toFixed(1)}T`
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(0)}M`
  return value.toLocaleString()
}

function colorClass(value: number | null, invertGood?: boolean): string {
  if (value === null) return 'text-muted-foreground'
  const isGood = invertGood ? value > 0 : value < 0
  if (Math.abs(value) < 5) return 'text-foreground'
  return isGood ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
}

function rsiColorClass(rsi: number | null): string {
  if (rsi === null) return 'text-muted-foreground'
  if (rsi < 35) return 'text-green-600 dark:text-green-400'
  if (rsi > 65) return 'text-red-600 dark:text-red-400'
  return 'text-foreground'
}

function scoreColorClass(score: number | null): string {
  if (score === null) return 'text-muted-foreground'
  if (score >= 70) return 'text-green-600 dark:text-green-400'
  if (score >= 40) return 'text-yellow-600 dark:text-yellow-400'
  return 'text-red-600 dark:text-red-400'
}

function scoreBgClass(score: number | null): string {
  if (score === null) return 'bg-muted'
  if (score >= 70) return 'bg-green-100 dark:bg-green-900/40'
  if (score >= 40) return 'bg-yellow-100 dark:bg-yellow-900/40'
  return 'bg-red-100 dark:bg-red-900/40'
}

const RATING_LABELS: Record<string, string> = {
  strong_buy: 'Strong Buy',
  buy: 'Buy',
  hold: 'Hold',
  sell: 'Sell',
  strong_sell: 'Strong Sell',
}

function ratingColorClass(rating: string | null): string {
  if (!rating) return 'text-muted-foreground'
  if (rating === 'strong_buy' || rating === 'buy') return 'text-green-600 dark:text-green-400'
  if (rating === 'hold') return 'text-yellow-600 dark:text-yellow-400'
  return 'text-red-600 dark:text-red-400'
}

type TooltipState = { label: string; description: string; formula?: string; x: number; y: number }

export function WatchlistTab() {
  const queryClient = useQueryClient()
  const [tickerInput, setTickerInput] = useState('')
  const [sortColumn, setSortColumn] = useState<SortColumn>('buy_score')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [headerTooltip, setHeaderTooltip] = useState<TooltipState | null>(null)

  const { data: items, isLoading } = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => api.getWatchlist(),
    staleTime: 5 * 60 * 1000,
  })

  const addMutation = useMutation({
    mutationFn: (ticker: string) => api.addToWatchlist(ticker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      setTickerInput('')
    },
  })

  const removeMutation = useMutation({
    mutationFn: (id: number) => api.removeFromWatchlist(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
  })

  const syncMutation = useMutation({
    mutationFn: () => api.syncWatchlist(true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
  })

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault()
    const ticker = tickerInput.trim().toUpperCase()
    if (ticker) {
      addMutation.mutate(ticker)
    }
  }

  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(column)
      setSortDirection('desc')
    }
  }

  const sortedItems = useMemo(() => {
    if (!items) return []
    return [...items].sort((a, b) => {
      const aVal = a[sortColumn]
      const bVal = b[sortColumn]
      if (aVal === null && bVal === null) return 0
      if (aVal === null) return 1
      if (bVal === null) return -1
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDirection === 'asc'
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal)
      }
      return sortDirection === 'asc'
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number)
    })
  }, [items, sortColumn, sortDirection])

  const SortHeader = ({
    column, label, className,
    tooltip,
  }: {
    column: SortColumn; label: string; className?: string
    tooltip?: { description: string; formula?: string }
  }) => (
    <th
      className={`px-3 py-2 text-left text-xs font-medium text-muted-foreground cursor-pointer hover:text-foreground select-none ${className || ''}`}
      onClick={() => handleSort(column)}
      onMouseEnter={tooltip ? (e) => {
        const rect = e.currentTarget.getBoundingClientRect()
        setHeaderTooltip({ label, ...tooltip, x: rect.left + rect.width / 2, y: rect.bottom })
      } : undefined}
      onMouseLeave={tooltip ? () => setHeaderTooltip(null) : undefined}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortColumn === column && (
          sortDirection === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
        )}
      </span>
    </th>
  )

  return (
    <div className="space-y-6">
      {/* Add Stock + Sync Controls */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Watchlist</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending}
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
              {syncMutation.isPending ? 'Syncing...' : 'Refresh All'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleAdd} className="flex gap-2">
            <input
              type="text"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value)}
              placeholder="Enter Yahoo Finance ticker (e.g. NVDA, MSFT, ASML.AS)"
              className="flex-1 px-3 py-2 rounded-md border border-input bg-background text-sm"
            />
            <Button type="submit" disabled={addMutation.isPending || !tickerInput.trim()} size="sm">
              <Plus className="h-4 w-4 mr-1" />
              {addMutation.isPending ? 'Adding...' : 'Add'}
            </Button>
          </form>

          {addMutation.isError && (
            <p className="text-sm text-red-600 dark:text-red-400 mt-2">
              {addMutation.error.message}
            </p>
          )}
          {syncMutation.isSuccess && (
            <p className="text-sm text-green-600 dark:text-green-400 mt-2">
              {syncMutation.data.message}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Watchlist Table */}
      {isLoading ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">Loading watchlist...</CardContent>
        </Card>
      ) : !sortedItems.length ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No stocks on your watchlist yet. Add a ticker above to get started.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <SortHeader column="symbol" label="Stock" className="min-w-[160px]" />
                    <SortHeader column="buy_score" label="Score" tooltip={{ description: "Composite score across four equally-weighted categories.", formula: "Valuation (25) + Technical (25) + Quality (25) + Analyst (25)" }} />
                    <SortHeader column="current_price" label="Price" />
                    <SortHeader column="analyst_rating" label="Analyst" tooltip={{ description: "Analyst consensus rating and mean price target upside. Source: Yahoo Finance." }} />
                    <SortHeader column="pct_from_52w_high" label="% 52w High" tooltip={{ description: "How far the current price is below the 52-week high. More negative = bigger drawdown from peak.", formula: "(Price − 52w High) ÷ 52w High × 100" }} />
                    <SortHeader column="rsi14" label="RSI" tooltip={{ description: "Relative Strength Index (14-day). Below 30 = oversold, above 70 = overbought.", formula: "Wilder RSI on 1-year daily closes" }} />
                    <SortHeader column="pct_from_ma200" label="vs MA200" tooltip={{ description: "Distance from the 200-day moving average. Below 0% = bearish trend, above = uptrend.", formula: "(Price − MA200) ÷ MA200 × 100" }} />
                    <SortHeader column="peg_ratio" label="PEG" tooltip={{ description: "Forward P/E divided by forward EPS growth rate. A PEG below 1 suggests the stock may be undervalued relative to its expected earnings growth.", formula: "P/E ÷ Fwd EPS Growth %" }} />
                    <SortHeader column="trailing_pe" label="P/E" tooltip={{ description: "Price divided by earnings per share over the last 12 months.", formula: "Price ÷ TTM EPS" }} />
                    <SortHeader column="forward_pe" label="Fwd P/E" tooltip={{ description: "Price divided by next-12-month analyst consensus EPS. Lower than trailing P/E = earnings expected to grow.", formula: "Price ÷ Next-12M EPS estimate" }} />
                    <SortHeader column="ev_to_ebitda" label="EV/EBITDA" tooltip={{ description: "Enterprise value relative to EBITDA. Below 10 = cheap, above 20 = expensive.", formula: "Enterprise Value ÷ TTM EBITDA" }} />
                    <SortHeader column="revenue_growth" label="Rev Grw" tooltip={{ description: "TTM revenue growth vs prior TTM (8+ quarters). Falls back to same-quarter YoY (5–7 quarters), then Yahoo Finance .info.", formula: "sum(Q1–4) ÷ sum(Q5–8) − 1, or Q[0] ÷ Q[4] − 1" }} />
                    <SortHeader column="earnings_growth" label="EPS Grw" tooltip={{ description: "TTM EPS/Net Income growth vs prior TTM (8+ quarters). Falls back to same-quarter YoY (5–7 quarters), then Yahoo Finance .info. Note: PEG uses Yahoo's separate 5-year analyst estimate, not this figure.", formula: "sum(Q1–4) ÷ sum(Q5–8) − 1, or Q[0] ÷ Q[4] − 1" }} />
                    <SortHeader column="fwd_revenue_growth" label="Fwd Rev" tooltip={{ description: "Analyst consensus revenue growth estimate for next 12 months.", formula: "revenue_estimate['+1y']['growth']" }} />
                    <SortHeader column="fwd_eps_growth" label="Fwd EPS" tooltip={{ description: "Analyst consensus EPS growth estimate for next 12 months.", formula: "growth_estimates['+1y']['stockTrend']" }} />
                    <SortHeader column="profit_margins" label="Margin" tooltip={{ description: "Net income as a percentage of revenue over the trailing 12 months.", formula: "Net Income ÷ Revenue (TTM)" }} />
                    <th
                      className="px-3 py-2 text-left text-xs font-medium text-muted-foreground cursor-default"
                      onMouseEnter={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect()
                        setHeaderTooltip({ label: 'Market Cap', description: 'Total market value of all outstanding shares. Displayed in native currency.', formula: 'Share Price × Shares Outstanding', x: rect.left + rect.width / 2, y: rect.bottom })
                      }}
                      onMouseLeave={() => setHeaderTooltip(null)}
                    >
                      Mkt Cap
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedItems.map((item) => {
                    const analystUpside = item.analyst_target && item.current_price && item.current_price > 0
                      ? ((item.analyst_target - item.current_price) / item.current_price * 100)
                      : null
                    return (
                    <tr key={item.id} className="border-b hover:bg-muted/50">
                      {/* Stock */}
                      <td className="px-3 py-2">
                        <div>
                          <div className="font-medium">{item.symbol || item.yahoo_ticker}</div>
                          <div className="text-xs text-muted-foreground truncate max-w-[140px]">
                            {item.company_name || item.yahoo_ticker}
                          </div>
                        </div>
                      </td>

                      {/* Buy Score */}
                      <td className="px-3 py-2">
                        {item.buy_score !== null ? (
                          <span className={`inline-flex items-center justify-center w-9 h-6 rounded text-xs font-bold ${scoreColorClass(item.buy_score)} ${scoreBgClass(item.buy_score)}`}>
                            {Math.round(item.buy_score)}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>

                      {/* Price */}
                      <td className="px-3 py-2 font-medium">
                        {formatCurrency(item.current_price, item.data_currency)}
                      </td>

                      {/* Analyst */}
                      <td className="px-3 py-2">
                        <div className={`text-xs font-medium ${ratingColorClass(item.analyst_rating)}`}>
                          {item.analyst_rating ? RATING_LABELS[item.analyst_rating] || item.analyst_rating : '-'}
                        </div>
                        {analystUpside !== null && (
                          <div className={`text-[10px] ${analystUpside > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                            {analystUpside >= 0 ? '+' : ''}{analystUpside.toFixed(0)}% upside
                            {item.analyst_count ? ` (${item.analyst_count})` : ''}
                          </div>
                        )}
                      </td>

                      {/* % from 52w High */}
                      <td className={`px-3 py-2 font-medium ${colorClass(item.pct_from_52w_high)}`}>
                        {formatPercent(item.pct_from_52w_high)}
                      </td>

                      {/* RSI */}
                      <td className={`px-3 py-2 font-medium ${rsiColorClass(item.rsi14)}`}>
                        {item.rsi14 !== null ? item.rsi14.toFixed(1) : '-'}
                      </td>

                      {/* vs 200d MA */}
                      <td className={`px-3 py-2 font-medium ${colorClass(item.pct_from_ma200)}`}>
                        {formatPercent(item.pct_from_ma200)}
                      </td>

                      {/* PEG — use stored value, fall back to P/E ÷ Fwd EPS growth % */}
                      <td className="px-3 py-2">
                        {(() => {
                          const peg = item.peg_ratio ?? (
                            item.trailing_pe && item.fwd_eps_growth && item.fwd_eps_growth > 0
                              ? item.trailing_pe / (item.fwd_eps_growth * 100)
                              : null
                          )
                          return peg !== null ? (
                            <span className={peg <= 1 ? 'text-green-600 dark:text-green-400' : peg > 2 ? 'text-red-600 dark:text-red-400' : ''}>
                              {peg.toFixed(2)}
                            </span>
                          ) : '-'
                        })()}
                      </td>

                      {/* P/E */}
                      <td className="px-3 py-2">
                        {item.trailing_pe !== null ? item.trailing_pe.toFixed(1) : '-'}
                      </td>

                      {/* Fwd P/E */}
                      <td className="px-3 py-2">
                        {item.forward_pe !== null ? item.forward_pe.toFixed(1) : '-'}
                      </td>

                      {/* EV/EBITDA */}
                      <td className="px-3 py-2">
                        {item.ev_to_ebitda !== null ? item.ev_to_ebitda.toFixed(1) : '-'}
                      </td>

                      {/* Revenue Growth */}
                      <td className={`px-3 py-2 ${colorClass(item.revenue_growth != null ? item.revenue_growth * 100 : null, true)}`}>
                        {item.revenue_growth != null ? `${(item.revenue_growth * 100).toFixed(1)}%` : '-'}
                      </td>

                      {/* EPS Growth */}
                      <td className={`px-3 py-2 ${colorClass(item.earnings_growth != null ? item.earnings_growth * 100 : null, true)}`}>
                        {item.earnings_growth != null ? `${(item.earnings_growth * 100).toFixed(1)}%` : '-'}
                      </td>

                      {/* Fwd Revenue Growth */}
                      <td className={`px-3 py-2 ${colorClass(item.fwd_revenue_growth != null ? item.fwd_revenue_growth * 100 : null, true)}`}>
                        {item.fwd_revenue_growth != null ? `${(item.fwd_revenue_growth * 100).toFixed(1)}%` : '-'}
                      </td>

                      {/* Fwd EPS Growth */}
                      <td className={`px-3 py-2 ${colorClass(item.fwd_eps_growth != null ? item.fwd_eps_growth * 100 : null, true)}`}>
                        {item.fwd_eps_growth != null ? `${(item.fwd_eps_growth * 100).toFixed(1)}%` : '-'}
                      </td>

                      {/* Margin */}
                      <td className="px-3 py-2">
                        {item.profit_margins !== null ? `${(item.profit_margins * 100).toFixed(1)}%` : '-'}
                      </td>

                      {/* Market Cap */}
                      <td className="px-3 py-2 text-muted-foreground">
                        {formatMarketCap(item.market_cap)}
                      </td>

                      {/* Remove */}
                      <td className="px-3 py-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => removeMutation.mutate(item.id)}
                          disabled={removeMutation.isPending}
                          className="h-7 w-7 p-0 text-muted-foreground hover:text-red-600"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Fixed-position header tooltip — renders outside overflow container */}
      {headerTooltip && (
        <div
          className="fixed z-[9999] w-60 pointer-events-none"
          style={{ left: headerTooltip.x, top: headerTooltip.y + 6, transform: 'translateX(-50%)' }}
        >
          <div className="rounded-xl bg-background/85 backdrop-blur-md border border-border/40 shadow-2xl p-3 text-xs">
            <div className="font-semibold text-foreground mb-1">{headerTooltip.label}</div>
            <div className="text-muted-foreground leading-relaxed">{headerTooltip.description}</div>
            {headerTooltip.formula && (
              <div className="mt-2 font-mono text-[10px] bg-muted/50 rounded-md px-2 py-1.5 text-muted-foreground/80">
                {headerTooltip.formula}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
