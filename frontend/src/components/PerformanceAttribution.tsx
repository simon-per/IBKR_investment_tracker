import { useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Cell,
  ResponsiveContainer,
} from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ChevronRight } from 'lucide-react'
import { formatCurrency } from '@/lib/utils'
import type { PerformanceAttributionResponse } from '@/lib/api'

interface PerformanceAttributionProps {
  data: PerformanceAttributionResponse | undefined
  isLoading: boolean
}

export function PerformanceAttribution({ data, isLoading }: PerformanceAttributionProps) {
  const [open, setOpen] = useState(false)

  // Build summary text for the header
  let summaryText: React.ReactNode = 'P&L contribution by security'
  if (data && data.attributions.length > 0) {
    summaryText = (
      <>
        Total P&L:{' '}
        <span className={data.total_pnl_eur >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
          {data.total_pnl_eur >= 0 ? '+' : ''}{formatCurrency(data.total_pnl_eur, 'EUR')}
        </span>
      </>
    )
  }

  // Filter and sort data for the chart
  const sorted = (() => {
    if (!data || data.attributions.length === 0) return []
    const filtered = data.attributions.filter(a => Math.abs(a.pnl_contribution_eur) >= 1)
    const positive = filtered.filter(a => a.pnl_contribution_eur >= 0).sort((a, b) => b.pnl_contribution_eur - a.pnl_contribution_eur)
    const negative = filtered.filter(a => a.pnl_contribution_eur < 0).sort((a, b) => b.pnl_contribution_eur - a.pnl_contribution_eur)
    return [...positive, ...negative]
  })()

  const chartHeight = Math.min(900, Math.max(300, sorted.length * 36))

  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2">
          <ChevronRight className={`h-5 w-5 text-muted-foreground transition-transform duration-200 ${open ? 'rotate-90' : ''}`} />
          <div>
            <CardTitle>Performance Attribution</CardTitle>
            <CardDescription>{summaryText}</CardDescription>
          </div>
        </div>
      </CardHeader>
      {open && (
        <CardContent>
          {isLoading ? (
            <div className="h-[400px] w-full animate-pulse rounded-md bg-muted" />
          ) : sorted.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">
              No significant P&L changes in this period.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={chartHeight}>
              <BarChart
                data={sorted}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis
                  type="number"
                  tickFormatter={(value: number) => {
                    if (Math.abs(value) >= 1000) {
                      return `${(value / 1000).toFixed(1)}k`
                    }
                    return value.toFixed(0)
                  }}
                  fontSize={12}
                />
                <YAxis
                  type="category"
                  dataKey="symbol"
                  width={70}
                  fontSize={12}
                  tick={{ fill: 'currentColor' }}
                />
                <Tooltip content={<AttributionTooltip />} />
                <ReferenceLine x={0} stroke="hsl(var(--muted-foreground))" strokeWidth={1} />
                <Bar dataKey="pnl_contribution_eur" radius={[0, 4, 4, 0]}>
                  {sorted.map((entry, index) => (
                    <Cell
                      key={index}
                      fill={entry.pnl_contribution_eur >= 0 ? '#16a34a' : '#dc2626'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      )}
    </Card>
  )
}

function AttributionTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: PerformanceAttributionResponse['attributions'][0] }> }) {
  if (!active || !payload || payload.length === 0) return null

  const d = payload[0].payload
  const isPositive = d.pnl_contribution_eur >= 0

  return (
    <div className="bg-popover border rounded-lg shadow-md p-3 text-sm space-y-1">
      <p className="font-semibold">{d.symbol}</p>
      <p className="text-muted-foreground text-xs">{d.description}</p>
      <div className="border-t pt-1 mt-1 space-y-0.5">
        <p>
          <span className="text-muted-foreground">P&L: </span>
          <span className={`font-medium ${isPositive ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
            {isPositive ? '+' : ''}{formatCurrency(d.pnl_contribution_eur, 'EUR')}
          </span>
        </p>
        <p>
          <span className="text-muted-foreground">Contribution: </span>
          <span>{d.contribution_percent.toFixed(1)}%</span>
        </p>
        <p>
          <span className="text-muted-foreground">Weight: </span>
          <span>{d.weight_percent.toFixed(1)}%</span>
        </p>
        {d.new_investment_eur > 0 && (
          <p>
            <span className="text-muted-foreground">New investment: </span>
            <span>{formatCurrency(d.new_investment_eur, 'EUR')}</span>
          </p>
        )}
      </div>
    </div>
  )
}
