import { useState, useMemo } from 'react'
import type { Position } from '@/lib/api'
import { formatPercent } from '@/lib/utils'
import { useFormatCurrency } from '@/lib/CurrencyContext'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DataTable, type Column } from '@/components/ui/DataTable'

interface PositionsListProps {
  positions: Position[]
  isLoading?: boolean
  isError?: boolean
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

const exchangeOf = (p: Position) => p.exchange || 'N/A'

const gainTone = (p: Position) =>
  p.gain_loss_eur >= 0 ? 'text-green-600' : 'text-red-600'

/**
 * The positions table, described once for both renderings.
 *
 * A factory rather than a module constant because every cell closes over the currency
 * formatter and the portfolio total — which is also what lets a test import the exact
 * array the component renders instead of a copy of it.
 *
 * Note where the two views legitimately differ. The desktop table stacks the exchange
 * under the symbol and the ISIN under the description; the card puts the symbol on its
 * title line and the other two in the detail grid, so those get `desktop: 'hide'`
 * companions. The *values* come from one place either way.
 */
export function positionColumns(deps: {
  formatCurrency: (value: number) => string
  totalMarketValue: number
}): Column<Position, SortColumn>[] {
  const { formatCurrency, totalMarketValue } = deps
  const weightOf = (p: Position) =>
    totalMarketValue > 0 ? (p.market_value_eur / totalMarketValue) * 100 : 0

  return [
    {
      key: 'symbol',
      header: 'Symbol',
      shortHeader: 'Symbol',
      sortKey: 'symbol',
      mobile: 'title',
      cell: (p, view) =>
        view === 'table' ? (
          <>
            <div className="font-medium">{p.symbol}</div>
            <div className="text-xs text-muted-foreground">{exchangeOf(p)}</div>
          </>
        ) : (
          p.symbol
        ),
    },
    {
      key: 'description',
      header: 'Description',
      shortHeader: 'Description',
      sortKey: 'description',
      mobile: 'meta',
      cellClassName: 'max-w-xs',
      cell: (p, view) =>
        view === 'table' ? (
          <>
            <div className="max-w-xs truncate text-sm">{p.description}</div>
            <div className="text-xs text-muted-foreground">{p.isin}</div>
          </>
        ) : (
          p.description
        ),
    },
    {
      key: 'rating',
      header: 'Rating',
      shortHeader: 'Rating',
      sortKey: 'rating',
      align: 'center',
      mobile: 'badge',
      cell: (p, view) =>
        !p.analyst_rating ? (
          // A table cell cannot be empty, so the dash is the desktop placeholder. In a
          // card it would be a stray "-" floating in the badge row, saying nothing.
          view === 'table' ? <div className="text-center text-xs text-muted-foreground">-</div> : null
        ) : (
          <div
            className="flex flex-col items-center gap-1"
            title={`Strong Buy: ${p.analyst_rating.strong_buy}, Buy: ${p.analyst_rating.buy}, Hold: ${p.analyst_rating.hold}, Sell: ${p.analyst_rating.sell}, Strong Sell: ${p.analyst_rating.strong_sell}`}
          >
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${getRatingBadgeColor(p.analyst_rating.consensus)}`}
            >
              {p.analyst_rating.consensus}
            </span>
            {/* The breakdown is rendered, not just in the `title=`, which is what makes
                it readable on a phone where no hover exists. */}
            <div className="text-[10px] text-muted-foreground flex gap-0.5">
              <span className="text-green-600 font-semibold">{p.analyst_rating.strong_buy}</span>
              <span>/</span>
              <span className="text-green-500 font-semibold">{p.analyst_rating.buy}</span>
              <span>/</span>
              <span className="text-yellow-600 font-semibold">{p.analyst_rating.hold}</span>
              <span>/</span>
              <span className="text-red-500 font-semibold">{p.analyst_rating.sell}</span>
              <span>/</span>
              <span className="text-red-600 font-semibold">{p.analyst_rating.strong_sell}</span>
            </div>
          </div>
        ),
    },
    {
      key: 'market_value',
      header: 'Market Value',
      shortHeader: 'Market Value',
      sortKey: 'market_value_eur',
      align: 'right',
      mobile: 'value',
      cell: (p) => formatCurrency(p.market_value_eur),
    },
    {
      key: 'gain_loss_percent',
      header: '%',
      shortHeader: 'Gain/Loss %',
      sortKey: 'gain_loss_percent',
      align: 'right',
      mobile: 'delta',
      tone: gainTone,
      cell: (p) => formatPercent(p.gain_loss_percent),
    },
    {
      key: 'quantity',
      header: 'Quantity',
      shortHeader: 'Quantity',
      sortKey: 'quantity',
      align: 'right',
      cell: (p) => p.quantity.toFixed(2),
    },
    {
      key: 'cost_basis',
      header: 'Cost Basis',
      shortHeader: 'Cost Basis',
      sortKey: 'cost_basis_eur',
      align: 'right',
      cell: (p) => formatCurrency(p.cost_basis_eur),
    },
    {
      key: 'gain_loss',
      header: 'Gain/Loss',
      shortHeader: 'Gain/Loss',
      sortKey: 'gain_loss_eur',
      align: 'right',
      tone: gainTone,
      cell: (p) => formatCurrency(p.gain_loss_eur),
    },
    {
      key: 'weight',
      header: 'Weight',
      shortHeader: 'Weight',
      sortKey: 'portfolio_percent',
      align: 'right',
      cellClassName: 'text-muted-foreground',
      cell: (p) => `${weightOf(p).toFixed(2)}%`,
    },
    // Carried by the desktop cells above as sub-lines, so they would be duplicated
    // there; on a phone they are the detail pairs that keep a dual-listed security
    // (ASML is two securities) tellable apart.
    {
      key: 'exchange',
      header: 'Exchange',
      shortHeader: 'Exchange',
      desktop: 'hide',
      cell: exchangeOf,
    },
    { key: 'isin', header: 'ISIN', shortHeader: 'ISIN', desktop: 'hide', cell: (p) => p.isin },
  ]
}

export function PositionsList({ positions, isLoading, isError }: PositionsListProps) {
  const formatCurrency = useFormatCurrency()
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

  const columns = useMemo(
    () => positionColumns({ formatCurrency, totalMarketValue }),
    [formatCurrency, totalMarketValue]
  )

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

  // A server error must not impersonate an empty portfolio — the sync CTA
  // below can't fix a backend that isn't answering.
  if (isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center text-muted-foreground py-8">
            Couldn't load positions — the backend didn't respond. It retries automatically.
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>Positions ({positions.length})</CardTitle>
      </CardHeader>
      <CardContent>
        <DataTable
          rows={sortedPositions}
          columns={columns}
          getRowKey={(p) => p.security_id}
          label="Positions table"
          density="comfortable"
          // Quantity, cost basis, gain and weight are what a review is for; the
          // exchange and ISIN are identifiers you go looking for, so they sit behind
          // the disclosure rather than adding a line to all 29 cards.
          detailLimit={4}
          sort={{ column: sortColumn, direction: sortDirection, onSort: handleSort }}
        />
      </CardContent>
    </Card>
  )
}
