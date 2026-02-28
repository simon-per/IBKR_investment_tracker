import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Treemap, ResponsiveContainer, Tooltip } from 'recharts'
import { api } from '@/lib/api'
import type { AllocationCategory } from '@/lib/api'
import { formatCurrency } from '@/lib/utils'
import { RefreshCw, X } from 'lucide-react'

// Semantic colors for sectors
const SECTOR_COLORS: Record<string, string> = {
  'Technology': '#3b82f6',
  'Information Technology': '#3b82f6',
  'Financials': '#10b981',
  'Financial Services': '#10b981',
  'Healthcare': '#ef4444',
  'Health Care': '#ef4444',
  'Consumer Cyclical': '#f59e0b',
  'Consumer Discretionary': '#f59e0b',
  'Industrials': '#6366f1',
  'Communications': '#8b5cf6',
  'Communication Services': '#8b5cf6',
  'Consumer Defensive': '#14b8a6',
  'Consumer Staples': '#14b8a6',
  'Energy': '#f97316',
  'Real Estate': '#84cc16',
  'Utilities': '#06b6d4',
  'Basic Materials': '#a855f7',
  'Materials': '#a855f7',
}

const REGION_COLORS: Record<string, string> = {
  'North America': '#3b82f6',
  'United States': '#3b82f6',
  'US': '#3b82f6',
  'USA': '#3b82f6',
  'Europe': '#10b981',
  'Asia Pacific': '#f59e0b',
  'Emerging Markets': '#ef4444',
  'Latin America': '#8b5cf6',
  'Middle East & Africa': '#f97316',
  'Canada': '#06b6d4',
  'China': '#ec4899',
  'Japan': '#eab308',
  'South Korea': '#14b8a6',
  'Korea': '#14b8a6',
  'United Kingdom': '#22c55e',
  'UK': '#22c55e',
  'Germany': '#84cc16',
  'Switzerland': '#a855f7',
  'Ireland': '#6366f1',
}

const FALLBACK_COLORS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#10b981', '#f97316', '#6366f1',
  '#84cc16', '#14b8a6', '#f43f5e', '#a855f7', '#eab308',
]

// Normalize sector names for consistency
const SECTOR_MAPPING: Record<string, string> = {
  'Information Technology': 'Technology',
  'Tech': 'Technology',
  'IT': 'Technology',
  'Financial Services': 'Financials',
  'Finance': 'Financials',
  'Health Care': 'Healthcare',
  'HealthCare': 'Healthcare',
  'Consumer Discretionary': 'Consumer Cyclical',
  'Consumer Staples': 'Consumer Defensive',
  'Communication Services': 'Communications',
  'Telecommunications': 'Communications',
  'Materials': 'Basic Materials',
}

const GEOGRAPHIC_MAPPING: Record<string, string> = {
  'US': 'North America', 'USA': 'North America', 'United States': 'North America',
  'Canada': 'North America', 'Mexico': 'North America',
  'Europe': 'Europe', 'European Union': 'Europe', 'EU': 'Europe',
  'Germany': 'Europe', 'France': 'Europe', 'UK': 'Europe', 'United Kingdom': 'Europe',
  'Switzerland': 'Europe', 'Netherlands': 'Europe', 'Ireland': 'Europe',
  'Spain': 'Europe', 'Italy': 'Europe', 'Sweden': 'Europe', 'Norway': 'Europe',
  'Denmark': 'Europe', 'Finland': 'Europe', 'Austria': 'Europe', 'Belgium': 'Europe', 'Poland': 'Europe',
  'China': 'Asia Pacific', 'Japan': 'Asia Pacific', 'South Korea': 'Asia Pacific', 'Korea': 'Asia Pacific',
  'India': 'Asia Pacific', 'Taiwan': 'Asia Pacific', 'Hong Kong': 'Asia Pacific',
  'Singapore': 'Asia Pacific', 'Australia': 'Asia Pacific', 'New Zealand': 'Asia Pacific',
  'Thailand': 'Asia Pacific', 'Malaysia': 'Asia Pacific', 'Indonesia': 'Asia Pacific',
  'Saudi Arabia': 'Middle East & Africa', 'UAE': 'Middle East & Africa', 'Israel': 'Middle East & Africa',
  'South Africa': 'Middle East & Africa',
  'Brazil': 'Latin America', 'Argentina': 'Latin America', 'Chile': 'Latin America',
}

function normalize(name: string, mapping: Record<string, string>): string {
  return mapping[name] || name
}

function getColor(name: string, colorMap: Record<string, string>, index: number): string {
  return colorMap[name] || FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

// Custom treemap content renderer
interface TreemapContentProps {
  x: number
  y: number
  width: number
  height: number
  name: string
  percentage: number
  fill: string
  depth: number
}

function CustomTreemapContent(props: TreemapContentProps) {
  const { x, y, width, height, name, percentage, fill, depth } = props
  if (depth !== 1) return null

  const showLabel = width > 60 && height > 30
  const showPct = width > 40 && height > 20

  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={fill}
        stroke="hsl(var(--background))"
        strokeWidth={2}
        rx={4}
        className="cursor-pointer transition-opacity hover:opacity-80"
      />
      {showLabel && (
        <text
          x={x + width / 2}
          y={y + height / 2 - (showPct ? 8 : 0)}
          textAnchor="middle"
          dominantBaseline="central"
          fill="#fff"
          fontSize={Math.min(14, width / 8)}
          fontWeight={600}
          className="pointer-events-none"
        >
          {name.length > width / 8 ? name.slice(0, Math.floor(width / 8)) + '...' : name}
        </text>
      )}
      {showPct && (
        <text
          x={x + width / 2}
          y={y + height / 2 + 12}
          textAnchor="middle"
          dominantBaseline="central"
          fill="rgba(255,255,255,0.85)"
          fontSize={Math.min(12, width / 9)}
          className="pointer-events-none"
        >
          {percentage.toFixed(1)}%
        </text>
      )}
    </g>
  )
}

// Merge allocation categories that share the same normalized name
function mergeAllocation(
  raw: Record<string, AllocationCategory>,
  mapping: Record<string, string>,
): Record<string, AllocationCategory> {
  const merged: Record<string, AllocationCategory> = {}

  for (const [name, cat] of Object.entries(raw)) {
    const normalized = normalize(name, mapping)
    if (!merged[normalized]) {
      merged[normalized] = { percentage: 0, market_value_eur: 0, positions: [] }
    }
    merged[normalized].percentage += cat.percentage
    merged[normalized].market_value_eur += cat.market_value_eur

    // Merge positions, combining same symbols
    for (const pos of cat.positions) {
      const existing = merged[normalized].positions.find(p => p.symbol === pos.symbol)
      if (existing) {
        existing.weight += pos.weight
        existing.market_value_eur += pos.market_value_eur
      } else {
        merged[normalized].positions.push({ ...pos })
      }
    }
  }

  // Sort by percentage descending
  const sorted = Object.entries(merged).sort((a, b) => b[1].percentage - a[1].percentage)
  const result: Record<string, AllocationCategory> = {}
  for (const [k, v] of sorted) {
    v.positions.sort((a, b) => b.weight - a.weight)
    result[k] = v
  }
  return result
}

// Drill-down panel showing positions within a category
function DrillDownPanel({
  categoryName,
  category,
  onClose,
}: {
  categoryName: string
  category: AllocationCategory
  onClose: () => void
}) {
  return (
    <Card className="mt-4 border-primary/20">
      <CardHeader className="pb-3">
        <div className="flex justify-between items-center">
          <div>
            <CardTitle className="text-lg">{categoryName}</CardTitle>
            <CardDescription>
              {category.percentage.toFixed(1)}% of portfolio · {formatCurrency(category.market_value_eur, 'EUR')}
            </CardDescription>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left py-2 font-medium">Symbol</th>
                <th className="text-left py-2 font-medium">Description</th>
                <th className="text-right py-2 font-medium">Weight</th>
                <th className="text-right py-2 font-medium">Value (EUR)</th>
                <th className="text-right py-2 font-medium">Type</th>
              </tr>
            </thead>
            <tbody>
              {category.positions.map((pos) => (
                <tr key={pos.symbol} className="border-b border-muted/50 last:border-0">
                  <td className="py-2 font-medium">{pos.symbol}</td>
                  <td className="py-2 text-muted-foreground max-w-[200px] truncate">{pos.description}</td>
                  <td className="py-2 text-right tabular-nums">{pos.weight.toFixed(1)}%</td>
                  <td className="py-2 text-right tabular-nums">{formatCurrency(pos.market_value_eur, 'EUR')}</td>
                  <td className="py-2 text-right">
                    {pos.is_etf_contribution && (
                      <span className="text-xs bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded">
                        ETF est.
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

// Treemap section component
function AllocationTreemap({
  title,
  description,
  allocation,
  colorMap,
  isLoading,
}: {
  title: string
  description: string
  allocation: Record<string, AllocationCategory>
  colorMap: Record<string, string>
  isLoading: boolean
}) {
  const [selected, setSelected] = useState<string | null>(null)

  const entries = Object.entries(allocation)
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-80 text-muted-foreground">Loading...</div>
        </CardContent>
      </Card>
    )
  }

  if (entries.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-80 text-muted-foreground">
            No data available. Click "Sync Now" to fetch allocation data.
          </div>
        </CardContent>
      </Card>
    )
  }

  const treemapData = entries.map(([name, cat], i) => ({
    name,
    size: cat.percentage,
    percentage: cat.percentage,
    market_value_eur: cat.market_value_eur,
    fill: getColor(name, colorMap, i),
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-2xl">{title}</CardTitle>
        <CardDescription>{description} · Click a section to see positions</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex gap-6 items-start">
          {/* Treemap */}
          <div className="flex-1 min-w-0" style={{ height: 400 }}>
            <ResponsiveContainer width="100%" height="100%">
              <Treemap
                data={treemapData}
                dataKey="size"
                aspectRatio={4 / 3}
                isAnimationActive={false}
                content={<CustomTreemapContent x={0} y={0} width={0} height={0} name="" percentage={0} fill="" depth={1} />}
                onClick={(node: any) => {
                  if (node?.name) {
                    setSelected(selected === node.name ? null : node.name)
                  }
                }}
              >
                <Tooltip
                  content={({ payload }) => {
                    if (!payload || payload.length === 0) return null
                    const d = payload[0].payload
                    return (
                      <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-lg text-sm">
                        <p className="font-semibold">{d.name}</p>
                        <p className="text-muted-foreground">{d.percentage?.toFixed(1)}%</p>
                        <p className="text-muted-foreground">{formatCurrency(d.market_value_eur, 'EUR')}</p>
                      </div>
                    )
                  }}
                />
              </Treemap>
            </ResponsiveContainer>
          </div>

          {/* Legend */}
          <div className="w-[200px] shrink-0 space-y-1.5 pt-2">
            {entries.map(([name, cat], i) => (
              <button
                key={name}
                onClick={() => setSelected(selected === name ? null : name)}
                className={`flex items-center gap-2 w-full text-left py-1 px-1.5 rounded transition-colors ${
                  selected === name ? 'bg-muted' : 'hover:bg-muted/50'
                }`}
              >
                <div
                  style={{
                    width: '12px',
                    height: '12px',
                    borderRadius: '3px',
                    backgroundColor: getColor(name, colorMap, i),
                    flexShrink: 0,
                  }}
                />
                <span className="text-sm truncate flex-1">{name}</span>
                <span className="text-sm font-semibold tabular-nums">{cat.percentage.toFixed(1)}%</span>
              </button>
            ))}
          </div>
        </div>

        {/* Drill-down panel */}
        {selected && allocation[selected] && (
          <DrillDownPanel
            categoryName={selected}
            category={allocation[selected]}
            onClose={() => setSelected(null)}
          />
        )}
      </CardContent>
    </Card>
  )
}

export function AllocationTab() {
  const queryClient = useQueryClient()

  const { data: allocation, isLoading } = useQuery({
    queryKey: ['allocation', 'portfolio'],
    queryFn: () => api.getPortfolioAllocation(),
  })

  const { data: status } = useQuery({
    queryKey: ['allocation', 'status'],
    queryFn: () => api.getAllocationStatus(),
  })

  const syncMutation = useMutation({
    mutationFn: () => api.syncAllocationData(false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['allocation'] })
    },
  })

  const needsSync = status && status.securities_without_data > 0

  // Merge and normalize allocation data
  const sectorAllocation = allocation?.sector_allocation
    ? mergeAllocation(allocation.sector_allocation, SECTOR_MAPPING)
    : {}

  const geoAllocation = allocation?.geographic_allocation
    ? mergeAllocation(allocation.geographic_allocation, GEOGRAPHIC_MAPPING)
    : {}

  const assetAllocation = allocation?.asset_type_allocation || {}

  return (
    <div className="space-y-6">
      {/* Sync Status */}
      {needsSync && (
        <Card className="border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                  Allocation data needs updating
                </p>
                <p className="text-sm text-yellow-700 dark:text-yellow-300 mt-1">
                  {status.securities_without_data} securities missing allocation data
                </p>
              </div>
              <Button
                onClick={() => syncMutation.mutate()}
                disabled={syncMutation.isPending}
                variant="outline"
              >
                {syncMutation.isPending ? (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    Syncing...
                  </>
                ) : (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4" />
                    Sync Now
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {syncMutation.isSuccess && (
        <Card className="border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950">
          <CardContent className="pt-6">
            <p className="text-sm text-green-800 dark:text-green-200">
              Sync successful! Updated {syncMutation.data.securities_updated} securities
            </p>
          </CardContent>
        </Card>
      )}

      {/* Sector Breakdown - Full Width Treemap */}
      <AllocationTreemap
        title="Sector Breakdown"
        description="Portfolio allocation by sector"
        allocation={sectorAllocation}
        colorMap={SECTOR_COLORS}
        isLoading={isLoading}
      />

      {/* Geographic and Asset Type side by side */}
      <div className="grid gap-6 lg:grid-cols-2">
        <AllocationTreemap
          title="Geographic Breakdown"
          description="Portfolio allocation by region"
          allocation={geoAllocation}
          colorMap={REGION_COLORS}
          isLoading={isLoading}
        />

        <AllocationTreemap
          title="Asset Type"
          description="Stocks vs ETFs"
          allocation={assetAllocation}
          colorMap={{
            'Stock': '#3b82f6',
            'ETF': '#22c55e',
            'Unknown': '#6b7280',
          }}
          isLoading={isLoading}
        />
      </div>
    </div>
  )
}
