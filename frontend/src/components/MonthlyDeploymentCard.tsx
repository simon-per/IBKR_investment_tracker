import { useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts'
import { Card, CardContent } from '@/components/ui/card'
import { CollapsibleCardHeader } from '@/components/ui/CollapsibleCardHeader'
import { useCurrencySymbol } from '@/lib/CurrencyContext'
import type { ContributionsResponse, ContributionMonthlyItem } from '@/lib/api'

interface MonthlyDeploymentCardProps {
  data: ContributionsResponse | undefined
  isLoading: boolean
  isError?: boolean
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2026-07" -> "Jul 26"
function monthLabel(month: string): string {
  const [y, m] = month.split('-')
  return `${MONTH_NAMES[parseInt(m, 10) - 1] ?? m} ${y.slice(2)}`
}

// Deployed and net are the same measure family, so two steps of one hue rather
// than two hues. This exact pair passes the palette validator's CVD-separation,
// chroma and lightness checks on both the light and dark surfaces.
const DEPLOYED_COLOR = '#1d4fd8'
const NET_COLOR = '#4a90f7'

type ChartRow = ContributionMonthlyItem & { label: string }

export function MonthlyDeploymentCard({ data, isLoading, isError }: MonthlyDeploymentCardProps) {
  const curSym = useCurrencySymbol()
  const [open, setOpen] = useState(false)

  const monthly = data?.monthly ?? []
  const chartData: ChartRow[] = monthly.map(m => ({ ...m, label: monthLabel(m.month) }))

  // Collapsed summary: last month + 12M average of capital deployed
  let summaryText: React.ReactNode = 'Capital deployed per month'
  if (isError) {
    summaryText = 'Could not load contributions'
  } else if (monthly.length > 0) {
    const last = monthly[monthly.length - 1]
    const window = monthly.slice(-12)
    const avg = window.reduce((sum, m) => sum + m.deployed_eur, 0) / window.length
    summaryText = (
      <>
        {monthLabel(last.month)}: {curSym}
        {last.deployed_eur.toLocaleString('en-US', { maximumFractionDigits: 0 })} deployed
        {' · '}12M avg: {curSym}
        {avg.toLocaleString('en-US', { maximumFractionDigits: 0 })}/mo
      </>
    )
  }

  return (
    <Card>
      <CollapsibleCardHeader
        open={open}
        onToggle={() => setOpen(o => !o)}
        title="Monthly Deployment"
        description={summaryText}
        contentId="monthly-deployment-content"
      />
      {open && (
        <CardContent id="monthly-deployment-content">
          {isLoading ? (
            <div className="h-[300px] w-full animate-pulse rounded-md bg-muted" />
          ) : isError ? (
            // A failed fetch must not read as "you have deployed no capital" — same
            // rule as PortfolioValueChart and PerformanceAttribution.
            <p className="text-muted-foreground text-center py-8">
              Couldn't load contributions — the backend didn't respond. It retries automatically.
            </p>
          ) : chartData.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">
              No contribution history yet.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" fontSize={12} tick={{ fill: 'currentColor' }} />
                <YAxis
                  fontSize={12}
                  tickFormatter={(value: number) => {
                    if (Math.abs(value) >= 1000) {
                      return `${(value / 1000).toFixed(1)}k`
                    }
                    return value.toFixed(0)
                  }}
                />
                <Tooltip content={<DeploymentTooltip />} />
                <Legend />
                <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeWidth={1} />
                <Bar dataKey="deployed_eur" name="Deployed" fill={DEPLOYED_COLOR} radius={[4, 4, 0, 0]} />
                <Bar dataKey="net_eur" name="Net (deployed − released)" fill={NET_COLOR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      )}
    </Card>
  )
}

function DeploymentTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: ChartRow }> }) {
  const curSym = useCurrencySymbol()
  if (!active || !payload || payload.length === 0) return null

  const d = payload[0].payload
  const released = d.deployed_eur - d.net_eur
  const fmt = (v: number) =>
    `${curSym}${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

  return (
    <div className="bg-popover border rounded-lg shadow-md p-3 text-sm space-y-1">
      <p className="font-semibold">{d.label}</p>
      <div className="border-t pt-1 mt-1 space-y-0.5">
        <p>
          <span className="text-muted-foreground">Deployed: </span>
          <span className="font-medium">{fmt(d.deployed_eur)}</span>
        </p>
        <p>
          <span className="text-muted-foreground">Net: </span>
          <span className="font-medium">{fmt(d.net_eur)}</span>
        </p>
        {released > 0.005 && (
          <p>
            <span className="text-muted-foreground">Released by sales: </span>
            <span>{fmt(released)}</span>
          </p>
        )}
      </div>
    </div>
  )
}
