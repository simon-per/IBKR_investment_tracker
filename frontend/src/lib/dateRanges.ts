/**
 * Chart time-range arithmetic.
 *
 * Extracted from Dashboard because every boundary there ran through
 * `new Date(...).toISOString().split('T')[0]`, which serialises **local** midnight as
 * UTC. In any positive-UTC-offset zone that lands on the previous day: Berlin asked
 * for `2025-12-31` where New York asked for `2026-01-01` on the same YTD click, so the
 * same portfolio reported different numbers by locale. The `end` boundary had it too —
 * between local midnight and 00:00 UTC, "today" resolved to yesterday.
 *
 * Everything here works in local calendar components and never touches `toISOString`.
 */

export type TimeRange = '1W' | 'MTD' | '1M' | '3M' | '6M' | 'YTD' | '1Y' | '2Y' | 'ALL'

export const TIME_RANGES: TimeRange[] = ['1W', 'MTD', '1M', '3M', '6M', 'YTD', '1Y', '2Y', 'ALL']

/**
 * Where ALL starts when the portfolio's real inception is not known yet — the first
 * tax lot on this account. Only a first-paint fallback: the live value comes from
 * `/api/portfolio/contributions`.first_contribution_date, because transferred lots keep
 * their **original** open_date and a prior-year backfill moves inception backwards.
 */
export const FALLBACK_INCEPTION = '2024-05-28'

/**
 * `/api/portfolio/value-over-time` rejects a span wider than this with a 400
 * (`portfolio.py`), so ALL clamps to it rather than asking for a range the server
 * will refuse. Only reachable once inception is more than five years back — which the
 * planned 2025 tax backfill moves it towards — and a truncated chart beats no chart.
 */
export const MAX_RANGE_DAYS = 365 * 5

/** `YYYY-MM-DD` from a date's *local* components. Never `toISOString`. */
export function toLocalISODate(d: Date): string {
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${month}-${day}`
}

/**
 * N days before `d`, as local calendar arithmetic.
 *
 * `Date.now() - n * 86_400_000` — what this replaces — is wrong across a DST boundary:
 * a 23- or 25-hour day makes the subtraction land on the wrong side of midnight, so a
 * "90 day" range is 89 or 91 days twice a year. `new Date(y, m, d - n)` normalises
 * through the local calendar and is exact.
 */
function daysBefore(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() - n)
}

export interface DateRange {
  start: string
  end: string
}

/**
 * The `[start, end]` a range button means, both as local `YYYY-MM-DD`.
 *
 * `end` is always today. The conventions are deliberate rather than accidental:
 * **YTD starts on 1 January** of the current local year and **MTD on the 1st** of the
 * current local month — the calendar reading of both, matching what the labels say.
 *
 * `inception` is the first tax lot's open date; ALL falls back to FALLBACK_INCEPTION
 * until it loads.
 */
export function rangeFor(range: TimeRange, now: Date, inception?: string | null): DateRange {
  const end = toLocalISODate(now)

  switch (range) {
    case '1W':
      return { start: toLocalISODate(daysBefore(now, 7)), end }
    case 'MTD':
      return { start: toLocalISODate(new Date(now.getFullYear(), now.getMonth(), 1)), end }
    case '1M':
      return { start: toLocalISODate(daysBefore(now, 30)), end }
    case '3M':
      return { start: toLocalISODate(daysBefore(now, 90)), end }
    case '6M':
      return { start: toLocalISODate(daysBefore(now, 180)), end }
    case 'YTD':
      return { start: toLocalISODate(new Date(now.getFullYear(), 0, 1)), end }
    case '1Y':
      return { start: toLocalISODate(daysBefore(now, 365)), end }
    case '2Y':
      return { start: toLocalISODate(daysBefore(now, 730)), end }
    case 'ALL': {
      const earliest = toLocalISODate(daysBefore(now, MAX_RANGE_DAYS))
      const start = inception || FALLBACK_INCEPTION
      return { start: start < earliest ? earliest : start, end }
    }
  }
}
