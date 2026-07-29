import type { PortfolioValuePoint } from './api'
import { externalFlow } from './portfolioKpis'

export interface MonthReturn {
  returnPercent: number
  startValue: number
  endValue: number
  newInvestment: number
}

/**
 * Modified Dietz return over one period of daily points, flows day-weighted.
 *
 * Flows come from `externalFlow`, which values a sale at its market proceeds.
 * Inferring them from the cost-basis line instead is wrong on every sale date:
 * cost basis falls by what the lot cost while market value falls by what it
 * sold for, so the difference prints as a fabricated loss — a same-day
 * rotation showed its realized gain as a negative monthly return.
 */
export function computeModifiedDietzReturn(points: PortfolioValuePoint[]): MonthReturn | null {
  if (points.length < 2) return null
  const startMV = points[0].market_value_eur
  const endMV = points[points.length - 1].market_value_eur
  if (startMV === 0) return null

  const totalDays = points.length - 1

  let netCashFlow = 0
  let weightedCashFlow = 0
  for (let i = 1; i < points.length; i++) {
    const cf = externalFlow(points[i - 1], points[i])
    if (cf !== 0) {
      netCashFlow += cf
      // Weight: the fraction of the period the flow was actually at work
      weightedCashFlow += cf * ((totalDays - i) / totalDays)
    }
  }

  const gain = endMV - startMV - netCashFlow
  const denominator = startMV + weightedCashFlow

  return {
    returnPercent: denominator > 0 ? (gain / denominator) * 100 : 0,
    startValue: startMV,
    endValue: endMV,
    newInvestment: netCashFlow,
  }
}
