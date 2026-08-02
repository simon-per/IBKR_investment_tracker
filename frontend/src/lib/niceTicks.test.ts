import { describe, expect, it } from 'vitest'
import { niceTicks } from './niceTicks'

describe('niceTicks', () => {
  it('produces round steps and brackets the data', () => {
    const { domain, ticks } = niceTicks(0, 47_300, 8)
    expect(domain[0]).toBeLessThanOrEqual(0)
    expect(domain[1]).toBeGreaterThanOrEqual(47_300)
    expect(ticks[0]).toBe(domain[0])
    expect(ticks[ticks.length - 1]).toBe(domain[1])
    for (const t of ticks) expect(Number.isInteger(t / 5000) || Number.isInteger(t)).toBe(true)
  })

  it('honours the target count, which is the whole point of the extraction', () => {
    // The old fixed 200/1000/2500/10000 ladder ignored this, which is why a 20k range
    // put eight labels into a 280px-tall phone chart.
    const wide = niceTicks(0, 20_000, 8)
    const narrow = niceTicks(0, 20_000, 4)
    expect(narrow.ticks.length).toBeLessThan(wide.ticks.length)
    expect(narrow.ticks.length).toBeGreaterThanOrEqual(3)
  })

  it('stays near the target across the ranges this portfolio actually spans', () => {
    // The band is what matters, not an exact hit: a nice step cannot land on every
    // count. What must not happen is a phone axis quietly carrying twice its target.
    for (const max of [800, 4_800, 12_500, 47_300, 260_000]) {
      for (const target of [4, 8]) {
        const n = niceTicks(0, max, target).ticks.length
        expect(n, `${max} @ ${target}`).toBeGreaterThanOrEqual(target - 2)
        expect(n, `${max} @ ${target}`).toBeLessThanOrEqual(target + 3)
      }
    }
  })

  it('handles a negative minimum — the profit/loss series goes below zero', () => {
    // The ForecastTab original clamped at 0 and never saw this case.
    const { domain, ticks } = niceTicks(-4_200, 11_800, 6)
    expect(domain[0]).toBeLessThanOrEqual(-4_200)
    expect(domain[1]).toBeGreaterThanOrEqual(11_800)
    expect(ticks.some(t => t < 0)).toBe(true)
    expect(ticks).toContain(0)
  })

  it('gives a flat series an axis with height instead of one repeated line', () => {
    const { domain, ticks } = niceTicks(500, 500, 5)
    expect(domain[0]).toBeLessThan(500)
    expect(domain[1]).toBeGreaterThan(500)
    expect(new Set(ticks).size).toBe(ticks.length)
  })

  it('does not accumulate floating-point drift across the tick run', () => {
    // `i += step` on a fractional step is how an axis label ends up reading
    // 2999.9999999999995.
    const { ticks } = niceTicks(0, 3, 10)
    for (const t of ticks) expect(Number(t.toFixed(10))).toBe(t)
  })

  it('refuses rather than throws on degenerate input', () => {
    expect(niceTicks(NaN, 10, 5).ticks.length).toBeGreaterThan(0)
    expect(niceTicks(0, Infinity, 5).ticks.length).toBeGreaterThan(0)
    expect(niceTicks(0, 10, 0).ticks.length).toBeGreaterThan(0)
  })
})
