import { describe, it, expect } from 'vitest'
import { rangeFor, toLocalISODate, FALLBACK_INCEPTION, MAX_RANGE_DAYS } from './dateRanges'

/**
 * `new Date(y, m, d, ...)` builds a *local* date, so these tests exercise whatever zone
 * the runner is in without mocking TZ. That is the point: the bug was that a local
 * date got serialised as UTC, and the fix is that no boundary here ever does.
 */

describe('toLocalISODate', () => {
  it('reads the local calendar, not the UTC one', () => {
    // Local midnight on 1 January. `toISOString()` on this yields 2025-12-31 in any
    // positive-offset zone — which is exactly what YTD used to send.
    expect(toLocalISODate(new Date(2026, 0, 1))).toBe('2026-01-01')
    // And 23:30 local on the 31st stays the 31st, where toISOString would say the 1st
    // in any negative-offset zone.
    expect(toLocalISODate(new Date(2026, 11, 31, 23, 30))).toBe('2026-12-31')
  })

  it('zero-pads month and day', () => {
    expect(toLocalISODate(new Date(2026, 2, 5))).toBe('2026-03-05')
  })
})

describe('rangeFor', () => {
  const now = new Date(2026, 6, 31, 14, 30) // 31 Jul 2026, local afternoon

  it('ends on today in local terms', () => {
    for (const r of ['1W', 'MTD', 'YTD', 'ALL'] as const) {
      expect(rangeFor(r, now).end).toBe('2026-07-31')
    }
  })

  it('ends on today even just after local midnight', () => {
    // The window where toISOString() reported yesterday in a positive-offset zone.
    expect(rangeFor('YTD', new Date(2026, 6, 31, 0, 15)).end).toBe('2026-07-31')
  })

  it('starts YTD on 1 January of the local year', () => {
    expect(rangeFor('YTD', now).start).toBe('2026-01-01')
  })

  it('starts MTD on the 1st of the local month', () => {
    expect(rangeFor('MTD', now).start).toBe('2026-07-01')
  })

  it('counts back exact days for the rolling ranges', () => {
    expect(rangeFor('1W', now).start).toBe('2026-07-24')
    expect(rangeFor('1M', now).start).toBe('2026-07-01')
    expect(rangeFor('3M', now).start).toBe('2026-05-02')
    expect(rangeFor('6M', now).start).toBe('2026-02-01')
    expect(rangeFor('1Y', now).start).toBe('2025-07-31')
    // 730 days, not "2 calendar years" — no leap day falls in this span.
    expect(rangeFor('2Y', now).start).toBe('2024-07-31')
  })

  it('counts exact days across a DST boundary', () => {
    // 30 Mar 2026 is the EU spring-forward. Day arithmetic on epoch milliseconds is off
    // by one here in a DST zone; local calendar arithmetic is not.
    const afterDst = new Date(2026, 3, 5)
    expect(rangeFor('1W', afterDst).start).toBe('2026-03-29')
  })

  it('handles a leap day without drifting', () => {
    expect(rangeFor('1Y', new Date(2024, 1, 29)).start).toBe('2023-03-01')
  })

  it('crosses a year boundary for MTD and YTD in January', () => {
    const jan = new Date(2026, 0, 8)
    expect(rangeFor('MTD', jan)).toEqual({ start: '2026-01-01', end: '2026-01-08' })
    expect(rangeFor('YTD', jan)).toEqual({ start: '2026-01-01', end: '2026-01-08' })
    // YTD and MTD coincide in January; the 1M rolling range does not.
    expect(rangeFor('1M', jan).start).toBe('2025-12-09')
  })

  it('starts ALL at the portfolio inception it is given', () => {
    expect(rangeFor('ALL', now, '2023-11-02').start).toBe('2023-11-02')
  })

  it('falls back to the known first lot only until inception loads', () => {
    expect(rangeFor('ALL', now).start).toBe(FALLBACK_INCEPTION)
    expect(rangeFor('ALL', now, null).start).toBe(FALLBACK_INCEPTION)
    expect(rangeFor('ALL', now, '').start).toBe(FALLBACK_INCEPTION)
  })

  it('clamps ALL to the span the backend will accept', () => {
    // A 2015 lot would otherwise make the default chart 400 rather than render.
    const { start } = rangeFor('ALL', now, '2015-01-01')
    expect(start).toBe('2021-08-01')
    const spanDays = (new Date(2026, 6, 31).getTime() - new Date(2021, 7, 1).getTime()) / 86_400_000
    expect(spanDays).toBeLessThanOrEqual(MAX_RANGE_DAYS)
  })

  it('leaves an inception inside the limit alone', () => {
    expect(rangeFor('ALL', now, '2024-05-28').start).toBe('2024-05-28')
  })

  it('always returns start <= end', () => {
    for (const r of ['1W', 'MTD', '1M', '3M', '6M', 'YTD', '1Y', '2Y', 'ALL'] as const) {
      const { start, end } = rangeFor(r, now, '2024-05-28')
      expect(start <= end).toBe(true)
    }
  })
})
