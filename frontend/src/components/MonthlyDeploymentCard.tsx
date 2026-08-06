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
import { useIsCompact } from '@/lib/useMediaQuery'

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
  const isCompact = useIsCompact()
  const [open, setOpen] = useState(false)

  const monthly = data?.monthly ?? []
  const chartData: ChartRow[] = monthly.map(m => ({ ...m, label: monthLabel(m.month) }))

  // Collapsed summary: last month + the 12M average of capital deployed.
  //
  // The average is READ from the server's 12m window, not recomputed here. It was
  // recomputed until 2026-08-05 as `monthly.slice(-12)` summed and divided by its own
  // length, which is the same quantity the strip directly above this card already
  // renders from `avg_deployed_per_month_eur` — two numbers under one name on one
  // screen, 16 apart on live data.
  //
  // Both halves of the recomputation were wrong in the same direction. `monthly` is
  // built from a dict keyed only by months with activity, so a quiet month is absent:
  // `slice(-12)` takes the last twelve *rows*, which can span more than twelve months,
  // and dividing by `window.length` then uses a divisor smaller than the months
  // covered. The server divides by the window's elapsed months, clamped to available
  // history, and says so via `partial`.
  const twelveMonth = data?.windows.find(w => w.label === '12m')
  let summaryText: React.ReactNode = 'Capital deployed per month'
  if (isError) {
    summaryText = 'Could not load contributions'
  } else if (monthly.length > 0) {
    const last = monthly[monthly.length - 1]
    summaryText = (
      <>
        {monthLabel(last.month)}: {curSym}
        {last.deployed_eur.toLocaleString('en-US', { maximumFractionDigits: 0 })} deployed
        {twelveMonth && (
          <>
            {' · '}
            {/* A four-month-old portfolio has no twelve-month average, and the server
                already refuses to pretend otherwise by clamping the divisor. Naming the
                window it actually measured is the matching honesty on this side. */}
            {twelveMonth.partial ? `${twelveMonth.months.toFixed(0)}M avg` : '12M avg'}: {curSym}
            {twelveMonth.avg_deployed_per_month_eur.toLocaleString('en-US', { maximumFractionDigits: 0 })}/mo
          </>
        )}
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
            <div className="h-[240px] w-full animate-pulse rounded-md bg-muted sm:h-[300px]" />
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
            <div className="h-[240px] w-full sm:h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 5, right: 8, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="label"
                  fontSize={12}
                  tick={{ fill: 'currentColor' }}
                  interval="preserveStartEnd"
                  minTickGap={isCompact ? 28 : 8}
                />
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
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeWidth={1} />
                <Bar dataKey="deployed_eur" name="Deployed" fill={DEPLOYED_COLOR} radius={[4, 4, 0, 0]} />
                {/* "Net", not "Net (deployed − released)": the long form is ~300px of legend in
                    a 324px box, and DeploymentTooltip already spells it out. */}
                <Bar dataKey="net_eur" name="Net" fill={NET_COLOR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            </div>
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
