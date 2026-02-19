import { useState, useMemo, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

const STORAGE_KEYS = {
  monthlyContribution: 'forecast.monthlyContribution',
  expectedReturn: 'forecast.expectedReturn',
  startFromZero: 'forecast.startFromZero',
  forecastYears: 'forecast.forecastYears',
}

function readNumber(key: string, fallback: number, min: number, max: number): number {
  const saved = localStorage.getItem(key)
  if (!saved) return fallback
  const val = Number(saved)
  if (!isFinite(val) || isNaN(val) || val < min || val > max) return fallback
  return val
}

export function ForecastTab() {
  const [monthlyContribution, setMonthlyContribution] = useState(() => readNumber(STORAGE_KEYS.monthlyContribution, 1000, 0, 1000000))
  const [expectedReturn, setExpectedReturn] = useState(() => readNumber(STORAGE_KEYS.expectedReturn, 8, 0, 30))
  const [startFromZero, setStartFromZero] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEYS.startFromZero)
    return saved === 'true'
  })
  const [forecastYears, setForecastYears] = useState(() => readNumber(STORAGE_KEYS.forecastYears, 10, 1, 30))

  // Save to localStorage whenever values change
  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.monthlyContribution, monthlyContribution.toString())
  }, [monthlyContribution])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.expectedReturn, expectedReturn.toString())
  }, [expectedReturn])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.startFromZero, startFromZero.toString())
  }, [startFromZero])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.forecastYears, forecastYears.toString())
  }, [forecastYears])

  // Fetch current portfolio value
  const { data: summary } = useQuery({
    queryKey: ['portfolio', 'summary'],
    queryFn: () => api.getPortfolioSummary(),
  })

  const currentValue = startFromZero ? 0 : (summary?.total_market_value_eur || 0)

  // Calculate projections
  const projections = useMemo(() => {
    const years = [1, 5, 10, 15, 20]
    const monthlyRate = expectedReturn / 100 / 12

    return years.map(year => {
      const months = year * 12

      // Future Value = PV(1+r)^t + PMT × [(1+r)^t - 1] / r
      const portfolioGrowth = currentValue * Math.pow(1 + monthlyRate, months)

      // Handle division by zero when monthlyRate is 0
      let contributionsGrowth = 0
      if (monthlyRate === 0) {
        contributionsGrowth = monthlyContribution * months
      } else {
        contributionsGrowth = monthlyContribution *
          ((Math.pow(1 + monthlyRate, months) - 1) / monthlyRate)
      }

      const futureValue = portfolioGrowth + contributionsGrowth
      const totalContributions = monthlyContribution * months
      const investmentGains = futureValue - currentValue - totalContributions

      // Guard against invalid numbers
      const safeValue = (val: number) => (!isFinite(val) || isNaN(val)) ? 0 : val

      return {
        year,
        futureValue: Math.round(safeValue(futureValue)),
        totalContributions: Math.round(safeValue(totalContributions)),
        investmentGains: Math.round(safeValue(investmentGains)),
        portfolioGrowth: Math.round(safeValue(portfolioGrowth)),
      }
    })
  }, [currentValue, monthlyContribution, expectedReturn])

  // Scenario comparison
  const scenarios = useMemo(() => {
    const months = forecastYears * 12
    const rates = [
      { name: 'Conservative', rate: 5 },
      { name: 'Moderate', rate: 8 },
      { name: 'Aggressive', rate: 12 },
    ]

    return rates.map(({ name, rate }) => {
      const monthlyRate = rate / 100 / 12
      const portfolioGrowth = currentValue * Math.pow(1 + monthlyRate, months)

      // Handle division by zero when monthlyRate is 0
      let contributionsGrowth = 0
      if (monthlyRate === 0) {
        contributionsGrowth = monthlyContribution * months
      } else {
        contributionsGrowth = monthlyContribution *
          ((Math.pow(1 + monthlyRate, months) - 1) / monthlyRate)
      }

      const futureValue = portfolioGrowth + contributionsGrowth
      const safeValue = !isFinite(futureValue) || isNaN(futureValue) ? 0 : futureValue

      return {
        name,
        rate,
        value: Math.round(safeValue),
      }
    })
  }, [currentValue, monthlyContribution, forecastYears])

  // Monthly progression data for chart
  const monthlyData = useMemo(() => {
    const months = forecastYears * 12
    const monthlyRate = expectedReturn / 100 / 12
    const data = []

    for (let month = 0; month <= months; month += 6) { // Every 6 months for cleaner chart
      const portfolioGrowth = currentValue * Math.pow(1 + monthlyRate, month)

      // Handle division by zero when monthlyRate is 0
      let contributionsGrowth = 0
      if (month > 0) {
        if (monthlyRate === 0) {
          contributionsGrowth = monthlyContribution * month
        } else {
          contributionsGrowth = monthlyContribution * ((Math.pow(1 + monthlyRate, month) - 1) / monthlyRate)
        }
      }

      const futureValue = portfolioGrowth + contributionsGrowth
      const totalContributions = currentValue + (monthlyContribution * month)

      // Guard against invalid numbers
      const safeValue = (val: number) => (!isFinite(val) || isNaN(val)) ? 0 : val

      data.push({
        month,
        year: (month / 12).toFixed(1),
        value: Math.round(safeValue(futureValue)),
        contributions: Math.round(safeValue(totalContributions)),
      })
    }

    return data
  }, [currentValue, monthlyContribution, expectedReturn, forecastYears])

  // Calculate dynamic Y-axis configuration — always produces ≤ 10 ticks
  const yAxisConfig = useMemo(() => {
    const TARGET_TICKS = 8

    if (monthlyData.length === 0) {
      return { domain: [0, 100000] as [number, number], ticks: [0, 50000, 100000] }
    }

    const maxValue = Math.max(...monthlyData.map(d => d.value), 0)

    if (!isFinite(maxValue) || isNaN(maxValue) || maxValue <= 0) {
      return { domain: [0, 100000] as [number, number], ticks: [0, 50000, 100000] }
    }

    // Pick a "nice" interval so we get roughly TARGET_TICKS ticks
    const rawInterval = maxValue / TARGET_TICKS
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawInterval)))
    const normalised = rawInterval / magnitude                // 1–10 range
    const niceStep = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10
    const tickInterval = niceStep * magnitude

    const domainMax = Math.ceil(maxValue / tickInterval) * tickInterval

    const ticks: number[] = []
    for (let i = 0; i <= domainMax; i += tickInterval) {
      ticks.push(i)
    }

    return { domain: [0, domainMax] as [number, number], ticks }
  }, [monthlyData])

  return (
    <div className="space-y-8">
      {/* Input Controls */}
      <Card>
        <CardHeader>
          <CardTitle>Forecast Parameters</CardTitle>
          <CardDescription>Adjust your assumptions to see projected portfolio growth</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {/* Forecast Years */}
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Forecast Period
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  value={forecastYears}
                  onChange={(e) => setForecastYears(Number(e.target.value))}
                  className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
                  min="1"
                  max="30"
                  step="1"
                />
                <span className="text-sm font-semibold text-muted-foreground min-w-[60px] text-right">{forecastYears} {forecastYears === 1 ? 'year' : 'years'}</span>
              </div>
            </div>

            {/* Monthly Contribution */}
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Monthly Contribution
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={monthlyContribution}
                  onChange={(e) => {
                    const val = Number(e.target.value)
                    if (!isNaN(val) && isFinite(val) && val >= 0 && val <= 1000000) {
                      setMonthlyContribution(val)
                    }
                  }}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                  min="0"
                  max="1000000"
                  step="100"
                />
                <span className="text-sm text-muted-foreground">EUR</span>
              </div>
            </div>

            {/* Expected Return */}
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Expected Annual Return
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={expectedReturn}
                  onChange={(e) => {
                    const val = Number(e.target.value)
                    if (!isNaN(val) && isFinite(val) && val >= 0 && val <= 30) {
                      setExpectedReturn(val)
                    }
                  }}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                  min="0"
                  max="30"
                  step="0.5"
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
            </div>

            {/* Starting Point */}
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Starting Point
              </label>
              <div className="flex items-center gap-2 h-10">
                <button
                  onClick={() => setStartFromZero(false)}
                  className={`flex-1 h-full rounded-md border text-sm font-medium transition-colors ${
                    !startFromZero
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-background hover:bg-accent hover:text-accent-foreground'
                  }`}
                >
                  Current (€{Math.round(summary?.total_market_value_eur || 0).toLocaleString()})
                </button>
                <button
                  onClick={() => setStartFromZero(true)}
                  className={`flex-1 h-full rounded-md border text-sm font-medium transition-colors ${
                    startFromZero
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-background hover:bg-accent hover:text-accent-foreground'
                  }`}
                >
                  €0
                </button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Projection Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Projected Portfolio Growth ({forecastYears} {forecastYears === 1 ? 'Year' : 'Years'})</CardTitle>
          <CardDescription>
            Based on {expectedReturn}% annual return and €{monthlyContribution.toLocaleString()} monthly contribution
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6">
          <ResponsiveContainer width="100%" height={640}>
            <AreaChart data={monthlyData}>
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis
                dataKey="year"
                label={{ value: 'Years', position: 'insideBottom', offset: -5 }}
                tick={{ fontSize: 12 }}
              />
              <YAxis
                domain={yAxisConfig.domain}
                ticks={yAxisConfig.ticks}
                tickFormatter={(value) => `€${(value / 1000).toFixed(0)}k`}
                tick={{ fontSize: 12 }}
                width={80}
              />
              <Tooltip
                formatter={(value: number | undefined) => value != null ? `€${value.toLocaleString()}` : '—'}
                labelFormatter={(label) => `Year ${label}`}
              />
              <Area
                type="monotone"
                dataKey="contributions"
                stackId="1"
                stroke="#94a3b8"
                fill="#94a3b8"
                name="Total Contributions"
              />
              <Area
                type="monotone"
                dataKey="value"
                stackId="2"
                stroke="#22c55e"
                fill="#22c55e"
                name="Portfolio Value"
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Projection Table */}
      <Card>
        <CardHeader>
          <CardTitle>Future Value Projections</CardTitle>
          <CardDescription>Portfolio growth milestones</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b text-sm text-muted-foreground">
                  <th className="text-left pb-3 font-medium">Time Horizon</th>
                  <th className="text-right pb-3 font-medium">Portfolio Value</th>
                  <th className="text-right pb-3 font-medium">Total Contributions</th>
                  <th className="text-right pb-3 font-medium">Investment Gains</th>
                </tr>
              </thead>
              <tbody>
                {projections.map((proj) => (
                  <tr key={proj.year} className="border-b">
                    <td className="py-3 font-medium">{proj.year} {proj.year === 1 ? 'Year' : 'Years'}</td>
                    <td className="py-3 text-right tabular-nums font-semibold text-green-600 dark:text-green-400">
                      €{proj.futureValue.toLocaleString()}
                    </td>
                    <td className="py-3 text-right tabular-nums">
                      €{proj.totalContributions.toLocaleString()}
                    </td>
                    <td className="py-3 text-right tabular-nums text-blue-600 dark:text-blue-400">
                      €{proj.investmentGains.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Scenario Comparison */}
      <Card>
        <CardHeader>
          <CardTitle>Scenario Comparison ({forecastYears}-Year Outlook)</CardTitle>
          <CardDescription>Different return rate scenarios</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {scenarios.map((scenario) => (
              <div key={scenario.name} className="flex items-center justify-between p-4 rounded-lg border">
                <div>
                  <div className="font-medium">{scenario.name}</div>
                  <div className="text-sm text-muted-foreground">{scenario.rate}% annual return</div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold text-green-600 dark:text-green-400">
                    €{scenario.value.toLocaleString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
