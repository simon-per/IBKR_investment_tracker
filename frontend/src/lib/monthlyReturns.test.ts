import { describe, expect, it } from 'vitest'
import { computeModifiedDietzReturn } from './monthlyReturns'
import type { PortfolioValuePoint } from './api'

function point(date: string, mv: number, cost: number, flow?: number): PortfolioValuePoint {
  return {
    date,
    cost_basis_eur: cost,
    market_value_eur: mv,
    gain_loss_eur: mv - cost,
    gain_loss_percent: cost > 0 ? ((mv - cost) / cost) * 100 : 0,
    external_flow_eur: flow,
  }
}

describe('computeModifiedDietzReturn', () => {
  it('returns plain price appreciation for a flowless month', () => {
    const r = computeModifiedDietzReturn([
      point('2026-03-01', 1000, 900, 0),
      point('2026-03-31', 1050, 900, 0),
    ])
    expect(r?.returnPercent).toBeCloseTo(5, 6)
  })

  it('a sale is not a loss', () => {
    // The regression: a lot bought at 110 sold for 200. Market value drops by
    // the proceeds (200), cost basis only by the cost (110). Inferring the flow
    // from the cost-basis line printed the 90 of realized gain as a −9% month.
    const r = computeModifiedDietzReturn([
      point('2026-03-01', 1000, 610, 0),
      point('2026-03-02', 800, 500, -200),
    ])
    expect(r?.returnPercent).toBeCloseTo(0, 6)
    expect(r?.newInvestment).toBe(-200)
  })

  it('a same-day rotation with a realized gain is flat, not negative', () => {
    // Sell A (cost 110) for 200, rebuy B at 200: the backend nets the day's
    // flow to zero. The cost-basis delta is +90, which used to read as a loss.
    const r = computeModifiedDietzReturn([
      point('2026-03-01', 1000, 610, 0),
      point('2026-03-02', 1000, 700, 0),
    ])
    expect(r?.returnPercent).toBeCloseTo(0, 6)
  })

  it('falls back to the cost-basis line when external_flow_eur is absent', () => {
    // Older payloads: right for purchases, which is all the fallback promises.
    const r = computeModifiedDietzReturn([
      point('2026-03-01', 1000, 1000),
      point('2026-03-02', 2010, 2000),
    ])
    expect(r?.returnPercent).toBeCloseTo(1, 6)
  })

  it('day-weights a mid-month flow', () => {
    // Flow of 300 lands after 1 of 2 days, so it earns half the period:
    // gain 130 over a denominator of 1000 + 300·0.5.
    const r = computeModifiedDietzReturn([
      point('2026-03-01', 1000, 1000, 0),
      point('2026-03-02', 1300, 1300, 300),
      point('2026-03-03', 1430, 1300, 0),
    ])
    expect(r?.returnPercent).toBeCloseTo((130 / 1150) * 100, 4)
  })

  it('refuses windows it cannot price', () => {
    expect(computeModifiedDietzReturn([point('2026-03-01', 1000, 1000, 0)])).toBeNull()
    expect(
      computeModifiedDietzReturn([
        point('2026-03-01', 0, 0, 0),
        point('2026-03-02', 500, 500, 500),
      ]),
    ).toBeNull()
  })
})
