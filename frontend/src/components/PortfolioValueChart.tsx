import { useState, useMemo, useEffect, useRef } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { PortfolioValuePoint, BenchmarkValuePoint } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import { useFormatCurrency, useCurrencySymbol } from '@/lib/CurrencyContext'
import { useIsCompact } from '@/lib/useMediaQuery'
import { niceTicks } from '@/lib/niceTicks'

/**
 * One height for the chart and its three placeholder states, so a range switch or a
 * fetch failure cannot make the page jump. 600px was the only value at every width,
 * which is 71% of an 844px phone screen.
 */
const CHART_BOX = 'h-[280px] sm:h-[420px] lg:h-[600px]'

export interface BenchmarkDataset {
  data: BenchmarkValuePoint[]
  name: string
  color: string
  key: string
}

interface PortfolioValueChartProps {
  data: PortfolioValuePoint[]
  benchmarks?: BenchmarkDataset[]
  isLoading?: boolean
  isError?: boolean
}

export function PortfolioValueChart({ data, benchmarks = [], isLoading, isError }: PortfolioValueChartProps) {
  const formatCurrency = useFormatCurrency()
  const curSym = useCurrencySymbol()
  const [showCostBasis, setShowCostBasis] = useState(true)
  const [showMarketValue, setShowMarketValue] = useState(true)
  const [showProfit, setShowProfit] = useState(true)
  const [visibleBenchmarks, setVisibleBenchmarks] = useState<Set<string>>(new Set())
  const seenBenchmarkKeys = useRef<Set<string>>(new Set())
  // Axis width, tick density and margins are Recharts props, not CSS — the one part of
  // going responsive that a media query cannot reach.
  const isCompact = useIsCompact()

  // Auto-enable benchmarks when they first appear in the data
  useEffect(() => {
    const newKeys = benchmarks
      .filter(b => b.data.length > 0 && !seenBenchmarkKeys.current.has(b.key))
      .map(b => b.key)

    if (newKeys.length > 0) {
      newKeys.forEach(k => seenBenchmarkKeys.current.add(k))
      setVisibleBenchmarks(prev => {
        const next = new Set(prev)
        newKeys.forEach(k => next.add(k))
        return next
      })
    }
  }, [benchmarks])

  const toggleBenchmark = (key: string) => {
    setVisibleBenchmarks(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const chartData = useMemo(() => {
    // Build lookups for each benchmark by date
    const benchmarkLookups: Record<string, Record<string, number>> = {}
    for (const b of benchmarks) {
      const lookup: Record<string, number> = {}
      for (const bp of b.data) {
        lookup[bp.date] = bp.benchmark_value_eur
      }
      benchmarkLookups[b.key] = lookup
    }

    return data.map(point => {
      const row: Record<string, number | string | null> = {
        cost_basis_eur: point.cost_basis_eur,
        market_value_eur: point.market_value_eur,
        profit_eur: point.market_value_eur - point.cost_basis_eur,
        date: point.date,
        dateFormatted: formatDate(point.date),
      }
      for (const b of benchmarks) {
        row[`bench_${b.key}`] = benchmarkLookups[b.key]?.[point.date] ?? null
      }
      return row
    })
  }, [data, benchmarks])

  const availableBenchmarks = benchmarks.filter(b => b.data.length > 0)

  /**
   * X tick labels.
   *
   * This used to return a label only on the 1st of a month and `''` otherwise. That
   * defeats recharts' own thinning, which drops ticks by *index*: over two years it
   * kept up to 24 full-length labels while the ticks between them were empty strings,
   * so `minTickGap` had nothing to measure and the labels collided.
   *
   * Every tick is labelled now and recharts thins by measured text width. Consequence
   * to expect on desktop too: ticks no longer land on month firsts. The conservative
   * alternative — keep the day-1 rule, raise `interval` — does not fix 2Y at 390px, so
   * it does not fix the problem.
   */
  const formatXAxisTick = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
  }

  // Custom tick formatter for Y axis
  const formatYAxisTick = (value: number) => {
    if (value === 0) return `${curSym}0`
    const absValue = Math.abs(value)
    if (absValue >= 1000) {
      return `${value < 0 ? '-' : ''}${curSym}${(absValue / 1000).toFixed(0)}k`
    }
    return `${curSym}${value.toFixed(0)}`
  }

  // Calculate dynamic Y axis domain and ticks based on data and visible lines
  const yAxisConfig = useMemo(() => {
    if (!chartData || chartData.length === 0) {
      return {
        domain: [0, 50000] as [number, number],
        ticks: [0, 10000, 20000, 30000, 40000, 50000]
      }
    }


    // Find the min and max values only from visible lines
    const allValues: number[] = []
    chartData.forEach(point => {
      if (showCostBasis) allValues.push(point.cost_basis_eur as number)
      if (showMarketValue) allValues.push(point.market_value_eur as number)
      if (showProfit) allValues.push(point.profit_eur as number)
      for (const b of availableBenchmarks) {
        if (visibleBenchmarks.has(b.key)) {
          const v = point[`bench_${b.key}`] as number | null
          if (v != null) allValues.push(v)
        }
      }
    })

    if (allValues.length === 0) {
      return {
        domain: [0, 50000] as [number, number],
        ticks: [0, 10000, 20000, 30000, 40000, 50000]
      }
    }

    const minValue = Math.min(...allValues)
    const maxValue = Math.max(...allValues)
    const range = maxValue - minValue

    // For very small ranges, zoom in more. Otherwise use 10% padding
    const absMax = Math.max(Math.abs(maxValue), Math.abs(minValue), 1)
    const paddingPercent = range / absMax < 0.05 ? 0.15 : 0.10

    // Calculate domain with padding (allow negative for profit line)
    const domainMin = minValue - range * paddingPercent
    const domainMax = maxValue + range * paddingPercent

    // The tick count is a property of how tall the chart is, not of the data. This
    // used to be a fixed 200/1000/2500/10000 step ladder chosen from the range alone,
    // which is how eight labels ended up 35px apart in a 280px-tall phone chart.
    return niceTicks(domainMin, domainMax, isCompact ? 4 : 8)
  }, [chartData, showCostBasis, showMarketValue, showProfit, visibleBenchmarks, availableBenchmarks, isCompact])

  if (isLoading) {
    return (
      <div className={`w-full ${CHART_BOX} flex items-center justify-center bg-muted/10 rounded-lg`}>
        <div className="text-muted-foreground">Loading chart data...</div>
      </div>
    )
  }

  // A server error must not impersonate an empty portfolio — the sync CTA
  // below can't fix a backend that isn't answering.
  if (isError) {
    return (
      <div className={`w-full ${CHART_BOX} flex items-center justify-center bg-muted/10 rounded-lg border border-dashed`}>
        <div className="text-center">
          <p className="text-muted-foreground">Couldn't load the chart</p>
          <p className="text-sm text-muted-foreground mt-2">
            The backend didn't respond — it may be redeploying. It retries automatically.
          </p>
        </div>
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div className={`w-full ${CHART_BOX} flex items-center justify-center bg-muted/10 rounded-lg border border-dashed`}>
        <div className="text-center">
          <p className="text-muted-foreground">No portfolio data available</p>
          <p className="text-sm text-muted-foreground mt-2">
            Sync your IBKR data to see your portfolio value over time
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Toggle Buttons. Already wrapping; the min-height is the touch target. */}
      <div className="flex gap-2 flex-wrap items-center sm:gap-3 [&>button]:min-h-11 sm:[&>button]:min-h-0">
        <span className="text-sm text-muted-foreground">Show:</span>
        <button
          onClick={() => setShowCostBasis(!showCostBasis)}
          className={`flex items-center gap-2 text-sm px-3 py-1.5 rounded-md transition-all ${
            showCostBasis
              ? 'bg-[#8b5cf6]/10 text-[#8b5cf6] font-medium'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
          }`}
        >
          <div className={`w-2.5 h-2.5 rounded-full ${showCostBasis ? 'bg-[#8b5cf6]' : 'bg-muted-foreground/30'}`} />
          Cost Basis
        </button>
        <button
          onClick={() => setShowMarketValue(!showMarketValue)}
          className={`flex items-center gap-2 text-sm px-3 py-1.5 rounded-md transition-all ${
            showMarketValue
              ? 'bg-[#22c55e]/10 text-[#22c55e] font-medium'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
          }`}
        >
          <div className={`w-2.5 h-2.5 rounded-full ${showMarketValue ? 'bg-[#22c55e]' : 'bg-muted-foreground/30'}`} />
          Market Value
        </button>
        <button
          onClick={() => setShowProfit(!showProfit)}
          className={`flex items-center gap-2 text-sm px-3 py-1.5 rounded-md transition-all ${
            showProfit
              ? 'bg-[#f59e0b]/10 text-[#f59e0b] font-medium'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
          }`}
        >
          <div className={`w-2.5 h-2.5 rounded-full ${showProfit ? 'bg-[#f59e0b]' : 'bg-muted-foreground/30'}`} />
          Profit/Loss
        </button>
        {availableBenchmarks.map(b => (
          <button
            key={b.key}
            onClick={() => toggleBenchmark(b.key)}
            className={`flex items-center gap-2 text-sm px-3 py-1.5 rounded-md transition-all ${
              visibleBenchmarks.has(b.key)
                ? `font-medium`
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            }`}
            style={visibleBenchmarks.has(b.key) ? { backgroundColor: `${b.color}15`, color: b.color } : undefined}
          >
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: visibleBenchmarks.has(b.key) ? b.color : 'hsl(var(--muted-foreground) / 0.3)' }} />
            {b.name}
          </button>
        ))}
      </div>

      {/* Chart. The height is CSS on the wrapper rather than a `height={600}` prop, so
          one class string covers the chart and its three placeholder states. */}
      <div className={`w-full ${CHART_BOX}`}>
      <ResponsiveContainer width="100%" height="100%">
        {/* `left: 20` double-padded a chart that already has a Y axis — 20px of a
            324px card. */}
        <LineChart data={chartData} margin={{ top: 5, right: isCompact ? 8 : 30, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          <XAxis
            dataKey="date"
            className="text-xs"
            tick={{ fill: 'hsl(var(--muted-foreground))' }}
            tickFormatter={formatXAxisTick}
            interval="preserveStartEnd"
            // Every tick is labelled now, so recharts can thin by measured text width.
            // See formatXAxisTick for why the old day-1 rule made that impossible.
            minTickGap={isCompact ? 44 : 60}
          />
          <YAxis
            className="text-xs"
            tick={{ fill: 'hsl(var(--muted-foreground))' }}
            tickFormatter={formatYAxisTick}
            domain={yAxisConfig.domain}
            ticks={yAxisConfig.ticks}
            // "€12k" is ~34px; the default 60 spends a fifth of a phone's plot area.
            width={isCompact ? 44 : 60}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'hsl(var(--card))',
              border: '1px solid hsl(var(--border))',
              borderRadius: '8px',
              // Recharts clamps a tooltip to the viewBox, so it never causes overflow —
              // but unbounded it fills the whole plot area at 390px.
              maxWidth: '70vw',
            }}
            formatter={(value: number | undefined) => value !== undefined ? formatCurrency(value) : ''}
          />
          {showCostBasis && (
            <Line
              type="monotone"
              dataKey="cost_basis_eur"
              stroke="#8b5cf6"
              strokeWidth={2}
              name="Cost Basis"
              dot={false}
              activeDot={{ r: 6 }}
            />
          )}
          {showMarketValue && (
            <Line
              type="monotone"
              dataKey="market_value_eur"
              stroke="#22c55e"
              strokeWidth={2}
              name="Market Value"
              dot={false}
              activeDot={{ r: 6 }}
            />
          )}
          {showProfit && (
            <Line
              type="monotone"
              dataKey="profit_eur"
              stroke="#f59e0b"
              strokeWidth={2}
              name="Profit/Loss"
              dot={false}
              activeDot={{ r: 6 }}
            />
          )}
          {availableBenchmarks.map(b =>
            visibleBenchmarks.has(b.key) ? (
              <Line
                key={b.key}
                type="monotone"
                dataKey={`bench_${b.key}`}
                stroke={b.color}
                strokeWidth={2}
                strokeDasharray="5 5"
                name={b.name}
                dot={false}
                activeDot={{ r: 6 }}
                connectNulls
              />
            ) : null
          )}
        </LineChart>
      </ResponsiveContainer>
      </div>
    </div>
  )
}
