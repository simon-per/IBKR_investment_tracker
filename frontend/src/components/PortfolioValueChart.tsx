import { useState, useMemo } from 'react'
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
import { formatCurrency, formatDate } from '@/lib/utils'

interface PortfolioValueChartProps {
  data: PortfolioValuePoint[]
  benchmarkData?: BenchmarkValuePoint[]
  benchmarkName?: string
  isLoading?: boolean
}

export function PortfolioValueChart({ data, benchmarkData, benchmarkName, isLoading }: PortfolioValueChartProps) {
  const [showCostBasis, setShowCostBasis] = useState(true)
  const [showMarketValue, setShowMarketValue] = useState(true)
  const [showProfit, setShowProfit] = useState(true)
  const [showBenchmark, setShowBenchmark] = useState(false)

  const chartData = useMemo(() => {
    // Build a lookup of benchmark values by date
    const benchmarkByDate: Record<string, number> = {}
    if (benchmarkData) {
      for (const bp of benchmarkData) {
        benchmarkByDate[bp.date] = bp.benchmark_value_eur
      }
    }

    return data.map(point => ({
      ...point,
      profit_eur: point.market_value_eur - point.cost_basis_eur,
      benchmark_value_eur: benchmarkByDate[point.date] ?? null,
      dateFormatted: formatDate(point.date),
    }))
  }, [data, benchmarkData])

  const hasBenchmark = benchmarkData && benchmarkData.length > 0

  // Custom tick formatter for X axis - show first day of each month
  const formatXAxisTick = (value: string) => {
    const date = new Date(value)
    const day = date.getDate()

    // Only show label for first day of month
    if (day === 1) {
      return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    }
    return ''
  }

  // Custom tick formatter for Y axis
  const formatYAxisTick = (value: number) => {
    if (value === 0) return '€0'
    const absValue = Math.abs(value)
    if (absValue >= 1000) {
      return `${value < 0 ? '-' : ''}€${(absValue / 1000).toFixed(0)}k`
    }
    return `€${value.toFixed(0)}`
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
      if (showCostBasis) allValues.push(point.cost_basis_eur)
      if (showMarketValue) allValues.push(point.market_value_eur)
      if (showProfit) allValues.push(point.profit_eur)
      if (showBenchmark && point.benchmark_value_eur != null) {
        allValues.push(point.benchmark_value_eur)
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

    // Determine appropriate tick step based on range
    let tickStep: number
    if (range < 1000) {
      tickStep = 200
    } else if (range < 5000) {
      tickStep = 1000
    } else if (range < 20000) {
      tickStep = 2500
    } else {
      tickStep = 10000
    }

    // Round domain to nice numbers
    const domainMinRounded = Math.floor(domainMin / tickStep) * tickStep
    const domainMaxRounded = Math.ceil(domainMax / tickStep) * tickStep

    // Generate ticks
    const ticks: number[] = []
    for (let i = domainMinRounded; i <= domainMaxRounded; i += tickStep) {
      ticks.push(i)
    }

    return {
      domain: [domainMinRounded, domainMaxRounded] as [number, number],
      ticks
    }
  }, [chartData, showCostBasis, showMarketValue, showProfit, showBenchmark])

  if (isLoading) {
    return (
      <div className="w-full h-[600px] flex items-center justify-center bg-muted/10 rounded-lg">
        <div className="text-muted-foreground">Loading chart data...</div>
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div className="w-full h-[600px] flex items-center justify-center bg-muted/10 rounded-lg border border-dashed">
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
      {/* Toggle Buttons */}
      <div className="flex gap-3 flex-wrap items-center">
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
        {hasBenchmark && (
          <button
            onClick={() => setShowBenchmark(!showBenchmark)}
            className={`flex items-center gap-2 text-sm px-3 py-1.5 rounded-md transition-all ${
              showBenchmark
                ? 'bg-[#3b82f6]/10 text-[#3b82f6] font-medium'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            }`}
          >
            <div className={`w-2.5 h-2.5 rounded-full ${showBenchmark ? 'bg-[#3b82f6]' : 'bg-muted-foreground/30'}`} />
            {benchmarkName || 'S&P 500'}
          </button>
        )}
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={600}>
        <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          <XAxis
            dataKey="date"
            className="text-xs"
            tick={{ fill: 'hsl(var(--muted-foreground))' }}
            tickFormatter={formatXAxisTick}
            interval="preserveStartEnd"
          />
          <YAxis
            className="text-xs"
            tick={{ fill: 'hsl(var(--muted-foreground))' }}
            tickFormatter={formatYAxisTick}
            domain={yAxisConfig.domain}
            ticks={yAxisConfig.ticks}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'hsl(var(--card))',
              border: '1px solid hsl(var(--border))',
              borderRadius: '8px',
            }}
            formatter={(value: number | undefined) => value !== undefined ? formatCurrency(value, 'EUR') : ''}
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
          {showBenchmark && (
            <Line
              type="monotone"
              dataKey="benchmark_value_eur"
              stroke="#3b82f6"
              strokeWidth={2}
              strokeDasharray="5 5"
              name={benchmarkName || 'S&P 500'}
              dot={false}
              activeDot={{ r: 6 }}
              connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
