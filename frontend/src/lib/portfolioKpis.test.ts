import { describe, expect, it } from 'vitest'
import {
  concentrationPct,
  dailyReturns,
  externalFlow,
  maxDrawdownPct,
  sharpeRatio,
} from './portfolioKpis'
import type { PortfolioValuePoint } from './api'

function point(
  date: string, mv: number, cost: number, flow?: number,
): PortfolioValuePoint {
  return {
    date,
    market_value_eur: mv,
    cost_basis_eur: cost,
    gain_loss_eur: mv - cost,
    gain_loss_percent: cost ? ((mv - cost) / cost) * 100 : 0,
    ...(flow === undefined ? {} : { external_flow_eur: flow }),
  }
}

describe('externalFlow', () => {
  it('uses the backend flow when present', () => {
    const prev = point('2026-01-01', 1000, 900)
    const curr = point('2026-01-02', 900, 800, -110)
    expect(externalFlow(prev, curr)).toBe(-110)
  })

  it('falls back to the cost-basis delta when the field is absent', () => {
    const prev = point('2026-01-01', 1000, 900)
    const curr = point('2026-01-02', 1100, 1000)
    expect(externalFlow(prev, curr)).toBe(100)
  })
})

describe('dailyReturns', () => {
  it('nets out a purchase so buying is not a gain', () => {
    // Bought 100 at market: value and cost both rise by 100, return is zero.
    const series = [point('2026-01-01', 1000, 1000), point('2026-01-02', 1100, 1100, 100)]
    expect(dailyReturns(series)[0]).toBeCloseTo(0, 10)
  })

  it('nets out a sale at proceeds, not at cost', () => {
    // A position bought for 50 is sold for 200: value drops 200, cost drops 50.
    // The real return that day is zero — nothing was lost, capital left.
    const series = [
      point('2026-01-01', 1000, 500),
      point('2026-01-02', 800, 450, -200),
    ]
    expect(dailyReturns(series)[0]).toBeCloseTo(0, 10)
  })

  it('without the backend flow, that same sale fabricates a loss', () => {
    // The regression this field exists to remove: inferring the flow from the
    // cost-basis line (−50) makes the day look like a 150 loss.
    const series = [
      point('2026-01-01', 1000, 500),
      point('2026-01-02', 800, 450),
    ]
    expect(dailyReturns(series)[0]).toBeLessThan(-0.1)
  })

  it('measures a real price move', () => {
    const series = [point('2026-01-01', 1000, 1000, 0), point('2026-01-02', 1100, 1000, 0)]
    expect(dailyReturns(series)[0]).toBeCloseTo(0.1, 10)
  })

  it('skips days with no value to divide by', () => {
    const series = [point('2026-01-01', 0, 0, 0), point('2026-01-02', 0, 0, 0)]
    expect(dailyReturns(series)).toEqual([])
  })
})

describe('maxDrawdownPct', () => {
  it('is zero for a series that only rises', () => {
    const series = [
      point('2026-01-01', 100, 100, 0),
      point('2026-01-02', 110, 100, 0),
      point('2026-01-03', 120, 100, 0),
    ]
    expect(maxDrawdownPct(series)).toBe(0)
  })

  it('reports the worst peak-to-trough fall, not the last one', () => {
    const series = [
      point('2026-01-01', 100, 100, 0),
      point('2026-01-02', 200, 100, 0),   // peak
      point('2026-01-03', 100, 100, 0),   // −50% from peak
      point('2026-01-04', 180, 100, 0),
      point('2026-01-05', 162, 100, 0),   // −10% from the later high
    ]
    expect(maxDrawdownPct(series)).toBeCloseTo(-50, 6)
  })

  it('a sale is not a drawdown', () => {
    const series = [
      point('2026-01-01', 1000, 500, 0),
      point('2026-01-02', 800, 450, -200),   // sold, did not fall
    ]
    expect(maxDrawdownPct(series)).toBeCloseTo(0, 6)
  })
})

describe('sharpeRatio', () => {
  it('returns 0 below the minimum sample', () => {
    const series = [point('2026-01-01', 100, 100, 0), point('2026-01-02', 101, 100, 0)]
    expect(sharpeRatio(series)).toBe(0)
  })

  it('is positive for steady gains and negative for steady losses', () => {
    const rising = [100, 101, 102, 103, 104, 105, 106].map((v, i) =>
      point(`2026-01-0${i + 1}`, v, 100, 0))
    const falling = [100, 99, 98, 97, 96, 95, 94].map((v, i) =>
      point(`2026-01-0${i + 1}`, v, 100, 0))
    expect(sharpeRatio(rising)).toBeGreaterThan(0)
    expect(sharpeRatio(falling)).toBeLessThan(0)
  })

  it('is clamped rather than exploding when volatility is negligible', () => {
    const series = Array.from({ length: 10 }, (_, i) =>
      point(`2026-01-${String(i + 1).padStart(2, '0')}`, 100 + i * 0.5, 100, 0))
    expect(Math.abs(sharpeRatio(series))).toBeLessThanOrEqual(10)
  })
})

describe('concentrationPct', () => {
  it('sums the largest N by value', () => {
    const positions = [10, 50, 20, 5, 5, 10].map((v) => ({ market_value_eur: v }))
    // top 5 of 100 total = 95
    expect(concentrationPct(positions)).toBeCloseTo(95, 6)
  })

  it('is 100% when there are fewer positions than N', () => {
    expect(concentrationPct([{ market_value_eur: 7 }])).toBeCloseTo(100, 6)
  })

  it('handles an empty portfolio', () => {
    expect(concentrationPct([])).toBe(0)
  })
})
