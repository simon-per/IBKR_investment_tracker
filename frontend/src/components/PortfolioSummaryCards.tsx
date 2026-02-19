import { TrendingUp, TrendingDown, Wallet, Target } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { PortfolioSummary } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'

interface PortfolioSummaryCardsProps {
  summary: PortfolioSummary | undefined
  isLoading?: boolean
}

export function PortfolioSummaryCards({ summary, isLoading }: PortfolioSummaryCardsProps) {
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Loading...</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-8 bg-muted animate-pulse rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  if (!summary) {
    return null
  }

  const isProfit = summary.total_gain_loss_eur >= 0

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Market Value</CardTitle>
          <Wallet className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">
            {formatCurrency(summary.total_market_value_eur, 'EUR')}
          </div>
          <p className="text-xs text-muted-foreground">
            Current portfolio value
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Cost Basis</CardTitle>
          <Target className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">
            {formatCurrency(summary.total_cost_basis_eur, 'EUR')}
          </div>
          <p className="text-xs text-muted-foreground">
            Total amount invested
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Unrealized Gain/Loss</CardTitle>
          {isProfit ? (
            <TrendingUp className="h-4 w-4 text-green-600" />
          ) : (
            <TrendingDown className="h-4 w-4 text-red-600" />
          )}
        </CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold ${isProfit ? 'text-green-600' : 'text-red-600'}`}>
            {formatCurrency(summary.total_gain_loss_eur, 'EUR')}
          </div>
          <p className="text-xs text-muted-foreground">
            {formatPercent(summary.total_gain_loss_percent)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{summary.num_positions}</div>
          <p className="text-xs text-muted-foreground">
            Unique securities held
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
