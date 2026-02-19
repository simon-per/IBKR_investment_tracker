import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { api } from '@/lib/api'
import { RefreshCw } from 'lucide-react'

const COLORS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#10b981', '#f97316', '#6366f1',
  '#84cc16', '#14b8a6', '#f43f5e', '#a855f7', '#eab308',
]

// Normalize geographic labels to consistent regions
const GEOGRAPHIC_MAPPING: Record<string, string> = {
  // North America
  'US': 'North America',
  'USA': 'North America',
  'United States': 'North America',
  'Canada': 'North America',
  'Mexico': 'North America',

  // Europe
  'Europe': 'Europe',
  'European Union': 'Europe',
  'EU': 'Europe',
  'Germany': 'Europe',
  'France': 'Europe',
  'UK': 'Europe',
  'United Kingdom': 'Europe',
  'Switzerland': 'Europe',
  'Netherlands': 'Europe',
  'Ireland': 'Europe',
  'Spain': 'Europe',
  'Italy': 'Europe',
  'Sweden': 'Europe',
  'Norway': 'Europe',
  'Denmark': 'Europe',
  'Finland': 'Europe',
  'Austria': 'Europe',
  'Belgium': 'Europe',
  'Poland': 'Europe',

  // Asia Pacific
  'China': 'Asia Pacific',
  'Japan': 'Asia Pacific',
  'South Korea': 'Asia Pacific',
  'Korea': 'Asia Pacific',
  'India': 'Asia Pacific',
  'Taiwan': 'Asia Pacific',
  'Hong Kong': 'Asia Pacific',
  'Singapore': 'Asia Pacific',
  'Australia': 'Asia Pacific',
  'New Zealand': 'Asia Pacific',
  'Thailand': 'Asia Pacific',
  'Malaysia': 'Asia Pacific',
  'Indonesia': 'Asia Pacific',
  'Philippines': 'Asia Pacific',
  'Vietnam': 'Asia Pacific',

  // Middle East & Africa
  'Saudi Arabia': 'Middle East & Africa',
  'UAE': 'Middle East & Africa',
  'United Arab Emirates': 'Middle East & Africa',
  'Israel': 'Middle East & Africa',
  'Qatar': 'Middle East & Africa',
  'Egypt': 'Middle East & Africa',
  'South Africa': 'Middle East & Africa',
  'Nigeria': 'Middle East & Africa',

  // Latin America
  'Brazil': 'Latin America',
  'Argentina': 'Latin America',
  'Chile': 'Latin America',
  'Colombia': 'Latin America',
  'Peru': 'Latin America',
}

function normalizeGeographicName(name: string): string {
  return GEOGRAPHIC_MAPPING[name] || name
}

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

  'Real Estate': 'Real Estate',

  'Materials': 'Basic Materials',
  'Basic Materials': 'Basic Materials',

  'Industrials': 'Industrials',

  'Energy': 'Energy',

  'Utilities': 'Utilities',
}

function normalizeSectorName(name: string): string {
  return SECTOR_MAPPING[name] || name
}

// Custom label to show percentage only for larger slices
const renderCustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }: any) => {
  if (percent < 0.05) return null // Don't show label for slices < 5%

  const RADIAN = Math.PI / 180
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5
  const x = cx + radius * Math.cos(-midAngle * RADIAN)
  const y = cy + radius * Math.sin(-midAngle * RADIAN)

  return (
    <text
      x={x}
      y={y}
      fill="white"
      textAnchor={x > cx ? 'start' : 'end'}
      dominantBaseline="central"
      className="font-semibold text-sm"
    >
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  )
}

export function AllocationTab() {
  const queryClient = useQueryClient()

  // Fetch allocation data
  const { data: allocation, isLoading } = useQuery({
    queryKey: ['allocation', 'portfolio'],
    queryFn: () => api.getPortfolioAllocation(),
  })

  // Fetch allocation status
  const { data: status } = useQuery({
    queryKey: ['allocation', 'status'],
    queryFn: () => api.getAllocationStatus(),
  })

  // Sync mutation
  const syncMutation = useMutation({
    mutationFn: () => api.syncAllocationData(false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['allocation'] })
    },
  })

  const handleSync = () => {
    syncMutation.mutate()
  }

  // Transform data for pie charts with normalization
  const sectorData = allocation?.sector_allocation
    ? Object.entries(
        Object.entries(allocation.sector_allocation).reduce((acc, [name, value]) => {
          const normalizedName = normalizeSectorName(name)
          acc[normalizedName] = (acc[normalizedName] || 0) + value
          return acc
        }, {} as Record<string, number>)
      )
        .map(([name, value]) => ({
          name,
          value: Number(value.toFixed(1)),
        }))
        .sort((a, b) => b.value - a.value) // Sort by value descending
    : []

  const geographicData = allocation?.geographic_allocation
    ? Object.entries(
        Object.entries(allocation.geographic_allocation).reduce((acc, [name, value]) => {
          const normalizedName = normalizeGeographicName(name)
          acc[normalizedName] = (acc[normalizedName] || 0) + value
          return acc
        }, {} as Record<string, number>)
      )
        .map(([name, value]) => ({
          name,
          value: Number(value.toFixed(1)),
        }))
        .sort((a, b) => b.value - a.value)
    : []

  const assetTypeData = allocation?.asset_type_allocation
    ? Object.entries(allocation.asset_type_allocation)
        .map(([name, value]) => ({
          name,
          value: Number(value.toFixed(1)),
        }))
        .sort((a, b) => b.value - a.value)
    : []

  const needsSync = status && status.securities_without_data > 0

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
                onClick={handleSync}
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

      {/* Sync Success Message */}
      {syncMutation.isSuccess && (
        <Card className="border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950">
          <CardContent className="pt-6">
            <p className="text-sm text-green-800 dark:text-green-200">
              ✓ Sync successful! Updated {syncMutation.data.securities_updated} securities
            </p>
          </CardContent>
        </Card>
      )}

      {/* Sector Breakdown - Full Width with Legend on Right */}
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Sector Breakdown</CardTitle>
          <CardDescription>Portfolio allocation by sector</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center h-96 text-muted-foreground">
              Loading...
            </div>
          ) : sectorData.length === 0 ? (
            <div className="flex items-center justify-center h-96 text-muted-foreground">
              No sector data available. Click "Sync Now" to fetch allocation data.
            </div>
          ) : (
            <div className="flex items-center">
              <div style={{ width: '55%', minWidth: 0, height: 480 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={sectorData}
                      cx="50%"
                      cy="50%"
                      labelLine={false}
                      label={renderCustomLabel}
                      outerRadius={180}
                      fill="#8884d8"
                      dataKey="value"
                    >
                      {sectorData.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value) => `${value}%`}
                      contentStyle={{
                        backgroundColor: '#ffffff',
                        border: '1px solid #e5e7eb',
                        borderRadius: '6px',
                        color: '#000000',
                      }}
                      labelStyle={{ color: '#000000' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div style={{ width: '45%', minWidth: 0 }}>
                {sectorData.map((item, index) => (
                  <div key={item.name} className="flex items-center gap-3 py-1.5 border-b border-muted last:border-0">
                    <div
                      style={{
                        width: '14px',
                        height: '14px',
                        borderRadius: '3px',
                        backgroundColor: COLORS[index % COLORS.length],
                        flexShrink: 0,
                      }}
                    />
                    <span className="text-sm font-medium flex-1 truncate">{item.name}</span>
                    <span className="text-sm font-semibold tabular-nums">{item.value}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Geographic Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Geographic Breakdown</CardTitle>
            <CardDescription>Portfolio allocation by region</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center justify-center h-80 text-muted-foreground">
                Loading...
              </div>
            ) : geographicData.length === 0 ? (
              <div className="flex items-center justify-center h-80 text-muted-foreground">
                No geographic data available.
              </div>
            ) : (
              <div className="flex flex-col">
                <div style={{ width: '100%', height: 320 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={geographicData}
                        cx="50%"
                        cy="50%"
                        labelLine={false}
                        label={renderCustomLabel}
                        outerRadius={120}
                        fill="#8884d8"
                        dataKey="value"
                      >
                        {geographicData.map((_, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value) => `${value}%`}
                        contentStyle={{
                          backgroundColor: '#ffffff',
                          border: '1px solid #e5e7eb',
                          borderRadius: '6px',
                          color: '#000000',
                        }}
                        labelStyle={{ color: '#000000' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pt-2">
                  {geographicData.map((item, index) => (
                    <div key={item.name} className="flex items-center gap-2">
                      <div
                        style={{
                          width: '10px',
                          height: '10px',
                          borderRadius: '2px',
                          backgroundColor: COLORS[index % COLORS.length],
                          flexShrink: 0,
                        }}
                      />
                      <span className="text-xs truncate flex-1">{item.name}</span>
                      <span className="text-xs font-semibold tabular-nums">{item.value}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Asset Type Distribution */}
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Asset Type Distribution</CardTitle>
            <CardDescription>Breakdown of stocks vs ETFs</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center justify-center h-80 text-muted-foreground">
                Loading...
              </div>
            ) : assetTypeData.length === 0 ? (
              <div className="flex items-center justify-center h-80 text-muted-foreground">
                No asset type data available
              </div>
            ) : (
              <div className="flex items-center">
                <div style={{ width: '65%', minWidth: 0, height: 320 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={assetTypeData}
                        cx="50%"
                        cy="50%"
                        labelLine={false}
                        label={renderCustomLabel}
                        outerRadius={120}
                        fill="#8884d8"
                        dataKey="value"
                      >
                        {assetTypeData.map((_, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value) => `${value}%`}
                        contentStyle={{
                          backgroundColor: '#ffffff',
                          border: '1px solid #e5e7eb',
                          borderRadius: '6px',
                          color: '#000000',
                        }}
                        labelStyle={{ color: '#000000' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ width: '35%', minWidth: 0 }}>
                  {assetTypeData.map((item, index) => (
                    <div key={item.name} className="flex items-center gap-2 py-2 border-b border-muted last:border-0">
                      <div
                        style={{
                          width: '14px',
                          height: '14px',
                          borderRadius: '3px',
                          backgroundColor: COLORS[index % COLORS.length],
                          flexShrink: 0,
                        }}
                      />
                      <span className="text-sm font-medium flex-1 truncate">{item.name}</span>
                      <span className="text-sm font-semibold tabular-nums">{item.value}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
