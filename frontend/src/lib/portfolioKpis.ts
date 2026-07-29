import type { PortfolioValuePoint } from './api'

/** Trading days per year, for annualising a daily return series. */
const TRADING_DAYS = 252
/** EUR risk-free assumption for the Sharpe numerator. */
const RISK_FREE_RATE = 0.03
/** Below this many daily returns the statistics are noise, not signal. */
const MIN_RETURNS = 5

/**
 * The day's external flow: money entering (+) or leaving (−) the holdings.
 *
 * Prefers the backend's `external_flow_eur`, which values a purchase at cost and
 * a sale at its market proceeds. The fallback — the change in the cost-basis
 * line — is right for purchases but wrong for sales: cost basis falls by what
 * the lot cost while market value falls by what it sold for, so the difference
 * shows up as a fabricated return on every sale date.
 */
export function externalFlow(prev: PortfolioValuePoint, curr: PortfolioValuePoint): number {
  if (typeof curr.external_flow_eur === 'number') return curr.external_flow_eur
  return curr.cost_basis_eur - prev.cost_basis_eur
}

/**
 * Modified-Dietz daily returns: the flow is assumed to arrive mid-day, so it
 * earns half the period.
 */
export function dailyReturns(series: PortfolioValuePoint[]): number[] {
  const out: number[] = []
  for (let i = 1; i < series.length; i++) {
    const prevMV = series[i - 1].market_value_eur
    const currMV = series[i].market_value_eur
    const cf = externalFlow(series[i - 1], series[i])
    const denominator = prevMV + cf * 0.5
    if (denominator > 0) out.push((currMV - prevMV - cf) / denominator)
  }
  return out
}

/** Worst peak-to-trough decline of the flow-adjusted value, as a negative percent. */
export function maxDrawdownPct(series: PortfolioValuePoint[]): number {
  let worst = 0
  let value = series.length ? series[0].market_value_eur : 0
  let peak = value
  for (const r of dailyReturns(series)) {
    value *= 1 + r
    if (value > peak) peak = value
    if (peak > 0) {
      const drawdown = ((value - peak) / peak) * 100
      if (drawdown < worst) worst = drawdown
    }
  }
  return worst
}

/** Annualised Sharpe of the daily return series; 0 when there isn't enough of it. */
export function sharpeRatio(series: PortfolioValuePoint[]): number {
  const returns = dailyReturns(series)
  if (returns.length < MIN_RETURNS) return 0

  const avg = returns.reduce((s, r) => s + r, 0) / returns.length
  const variance = returns.reduce((s, r) => s + (r - avg) ** 2, 0) / returns.length
  const annualisedStdDev = Math.sqrt(variance) * Math.sqrt(TRADING_DAYS)
  if (annualisedStdDev <= 0.001) return 0

  const ratio = (avg * TRADING_DAYS - RISK_FREE_RATE) / annualisedStdDev
  return Math.max(-10, Math.min(10, ratio))
}

/** Share of market value held in the largest N positions, as a percent. */
export function concentrationPct(
  positions: { market_value_eur: number }[],
  topN: number = 5,
): number {
  const total = positions.reduce((s, p) => s + p.market_value_eur, 0)
  if (total <= 0) return 0
  const top = [...positions]
    .sort((a, b) => b.market_value_eur - a.market_value_eur)
    .slice(0, topN)
    .reduce((s, p) => s + p.market_value_eur, 0)
  return (top / total) * 100
}
