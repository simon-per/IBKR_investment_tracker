import { useState, useMemo } from 'react'
import type { Position } from '@/lib/api'
import { formatCurrency, formatPercent } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'

interface PositionsListProps {
  positions: Position[]
  isLoading?: boolean
}

type SortColumn = 'symbol' | 'description' | 'rating' | 'quantity' | 'cost_basis_eur' | 'market_value_eur' | 'gain_loss_eur' | 'gain_loss_percent' | 'portfolio_percent'
type SortDirection = 'asc' | 'desc'

const getRatingBadgeColor = (consensus: string): string => {
  switch (consensus.toLowerCase()) {
    case 'strong buy':
      return 'bg-green-600 text-white'
    case 'buy':
      return 'bg-green-500 text-white'
    case 'hold':
      return 'bg-yellow-500 text-white'
    case 'sell':
      return 'bg-red-500 text-white'
    case 'strong sell':
      return 'bg-red-600 text-white'
    default:
      return 'bg-gray-500 text-white'
  }
}

// Convert rating consensus to numeric score for sorting (lower is better)
const getRatingScore = (consensus: string | undefined): number => {
  if (!consensus) return 999 // No rating goes to the bottom
  switch (consensus.toLowerCase()) {
    case 'strong buy':
      return 1
    case 'buy':
      return 2
    case 'hold':
      return 3
    case 'sell':
      return 4
    case 'strong sell':
      return 5
    default:
      return 999
  }
}

export function PositionsList({ positions, isLoading }: PositionsListProps) {
  const [sortColumn, setSortColumn] = useState<SortColumn>('market_value_eur')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  // Calculate total portfolio market value for percentage calculations
  const totalMarketValue = useMemo(() => {
    if (!positions || positions.length === 0) return 0
    return positions.reduce((sum, pos) => sum + pos.market_value_eur, 0)
  }, [positions])

  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      // Toggle direction if clicking the same column
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      // Default to descending for new column
      setSortColumn(column)
      setSortDirection('desc')
    }
  }

  const sortedPositions = useMemo(() => {
    if (!positions || positions.length === 0) return []

    const sorted = [...positions].sort((a, b) => {
      let aValue: string | number
      let bValue: string | number

      switch (sortColumn) {
        case 'symbol':
          aValue = a.symbol.toLowerCase()
          bValue = b.symbol.toLowerCase()
          break
        case 'description':
          aValue = a.description.toLowerCase()
          bValue = b.description.toLowerCase()
          break
        case 'rating':
          aValue = getRatingScore(a.analyst_rating?.consensus)
          bValue = getRatingScore(b.analyst_rating?.consensus)
          break
        case 'quantity':
          aValue = a.quantity
          bValue = b.quantity
          break
        case 'cost_basis_eur':
          aValue = a.cost_basis_eur
          bValue = b.cost_basis_eur
          break
        case 'market_value_eur':
          aValue = a.market_value_eur
          bValue = b.market_value_eur
          break
        case 'gain_loss_eur':
          aValue = a.gain_loss_eur
          bValue = b.gain_loss_eur
          break
        case 'gain_loss_percent':
          aValue = a.gain_loss_percent
          bValue = b.gain_loss_percent
          break
        case 'portfolio_percent':
          aValue = totalMarketValue > 0 ? (a.market_value_eur / totalMarketValue) * 100 : 0
          bValue = totalMarketValue > 0 ? (b.market_value_eur / totalMarketValue) * 100 : 0
          break
        default:
          return 0
      }

      if (aValue < bValue) return sortDirection === 'asc' ? -1 : 1
      if (aValue > bValue) return sortDirection === 'asc' ? 1 : -1
      return 0
    })

    return sorted
  }, [positions, sortColumn, sortDirection])

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center text-muted-foreground py-8">
            Loading positions...
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!positions || positions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center text-muted-foreground py-8">
            No positions found. Sync your IBKR data to see your holdings.
          </div>
        </CardContent>
      </Card>
    )
  }

  const SortableHeader = ({ column, label, align = 'left' }: { column: SortColumn; label: string; align?: 'left' | 'right' }) => {
    const isActive = sortColumn === column
    const alignClass = align === 'right' ? 'justify-end' : 'justify-start'

    return (
      <th className={`pb-3 font-medium ${align === 'right' ? 'text-right' : ''}`}>
        <button
          onClick={() => handleSort(column)}
          className={`flex items-center gap-1 ${alignClass} w-full hover:text-foreground transition-colors ${
            isActive ? 'text-foreground' : ''
          }`}
        >
          <span>{label}</span>
          {isActive ? (
            sortDirection === 'asc' ? (
              <ArrowUp className="h-4 w-4" />
            ) : (
              <ArrowDown className="h-4 w-4" />
            )
          ) : (
            <ArrowUpDown className="h-4 w-4 opacity-30" />
          )}
        </button>
      </th>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Positions ({positions.length})</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border text-left text-sm text-muted-foreground">
                <SortableHeader column="symbol" label="Symbol" />
                <SortableHeader column="description" label="Description" />
                <th className="pb-3 font-medium text-center">
                  <button
                    onClick={() => handleSort('rating')}
                    className={`flex items-center gap-1 justify-center w-full hover:text-foreground transition-colors ${
                      sortColumn === 'rating' ? 'text-foreground' : ''
                    }`}
                  >
                    <span>Rating</span>
                    {sortColumn === 'rating' ? (
                      sortDirection === 'asc' ? (
                        <ArrowUp className="h-4 w-4" />
                      ) : (
                        <ArrowDown className="h-4 w-4" />
                      )
                    ) : (
                      <ArrowUpDown className="h-4 w-4 opacity-30" />
                    )}
                  </button>
                </th>
                <SortableHeader column="quantity" label="Quantity" align="right" />
                <SortableHeader column="cost_basis_eur" label="Cost Basis" align="right" />
                <SortableHeader column="market_value_eur" label="Market Value" align="right" />
                <SortableHeader column="gain_loss_eur" label="Gain/Loss" align="right" />
                <SortableHeader column="gain_loss_percent" label="%" align="right" />
                <SortableHeader column="portfolio_percent" label="Weight" align="right" />
              </tr>
            </thead>
            <tbody>
              {sortedPositions.map((position) => {
                const isProfit = position.gain_loss_eur >= 0
                const portfolioPercent = totalMarketValue > 0 ? (position.market_value_eur / totalMarketValue) * 100 : 0
                return (
                  <tr key={position.security_id} className="border-b border-border last:border-0">
                    <td className="py-3">
                      <div className="font-medium">{position.symbol}</div>
                      <div className="text-xs text-muted-foreground">
                        {position.exchange || 'N/A'}
                      </div>
                    </td>
                    <td className="py-3">
                      <div className="max-w-xs truncate text-sm">{position.description}</div>
                      <div className="text-xs text-muted-foreground">{position.isin}</div>
                    </td>
                    <td className="py-3">
                      {position.analyst_rating ? (
                        <div className="flex flex-col items-center gap-1" title={`Strong Buy: ${position.analyst_rating.strong_buy}, Buy: ${position.analyst_rating.buy}, Hold: ${position.analyst_rating.hold}, Sell: ${position.analyst_rating.sell}, Strong Sell: ${position.analyst_rating.strong_sell}`}>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${getRatingBadgeColor(position.analyst_rating.consensus)}`}>
                            {position.analyst_rating.consensus}
                          </span>
                          <div className="text-[10px] text-muted-foreground flex gap-0.5">
                            <span className="text-green-600 font-semibold">{position.analyst_rating.strong_buy}</span>
                            <span>/</span>
                            <span className="text-green-500 font-semibold">{position.analyst_rating.buy}</span>
                            <span>/</span>
                            <span className="text-yellow-600 font-semibold">{position.analyst_rating.hold}</span>
                            <span>/</span>
                            <span className="text-red-500 font-semibold">{position.analyst_rating.sell}</span>
                            <span>/</span>
                            <span className="text-red-600 font-semibold">{position.analyst_rating.strong_sell}</span>
                          </div>
                        </div>
                      ) : (
                        <div className="text-center text-xs text-muted-foreground">-</div>
                      )}
                    </td>
                    <td className="py-3 text-right tabular-nums">
                      {position.quantity.toFixed(2)}
                    </td>
                    <td className="py-3 text-right tabular-nums">
                      {formatCurrency(position.cost_basis_eur, 'EUR')}
                    </td>
                    <td className="py-3 text-right tabular-nums">
                      {formatCurrency(position.market_value_eur, 'EUR')}
                    </td>
                    <td className={`py-3 text-right tabular-nums ${isProfit ? 'text-green-600' : 'text-red-600'}`}>
                      {formatCurrency(position.gain_loss_eur, 'EUR')}
                    </td>
                    <td className={`py-3 text-right tabular-nums ${isProfit ? 'text-green-600' : 'text-red-600'}`}>
                      {formatPercent(position.gain_loss_percent)}
                    </td>
                    <td className="py-3 text-right tabular-nums text-muted-foreground">
                      {portfolioPercent.toFixed(2)}%
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
