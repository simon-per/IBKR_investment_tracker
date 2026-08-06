// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { PerformanceMetricsCards } from './PerformanceMetricsCards'

/**
 * This row had no test until effective holdings moved onto it.
 *
 * The footnote it moved into is the interesting part: `top5Weight` is a confident number
 * whenever positions exist, while `effectiveHoldings` is `null` when none of them is
 * priced (`herfindahlConcentration` refuses rather than counting a zero-valued row as a
 * small one). So the two can disagree about whether there is anything to say, and
 * concatenating them without checking prints `· null effective` under a `0.0%`.
 */

afterEach(cleanup)

type Metrics = Parameters<typeof PerformanceMetricsCards>[0]['metrics']

const base: NonNullable<Metrics> = {
  xirr: 12.4,
  xirrMethod: 'xirr',
  maxDrawdown: -12.5,
  sharpeRatio: 1.21,
  winRate: 61,
  profitablePositions: 22,
  totalPositions: 36,
  calmarRatio: 0.99,
  top5Weight: 63.4,
  effectiveHoldings: 12.3,
}

function renderWith(overrides: Partial<NonNullable<Metrics>> = {}) {
  return render(<PerformanceMetricsCards metrics={{ ...base, ...overrides }} />)
}

describe('PerformanceMetricsCards', () => {
  it('footnotes the effective holdings beside the concentration it qualifies', () => {
    renderWith()
    expect(screen.getByText('63.4%')).toBeTruthy()
    expect(screen.getByText('Concentration risk · 12.3 effective')).toBeTruthy()
  })

  it('drops the count rather than printing an absent one', () => {
    renderWith({ effectiveHoldings: null })
    expect(screen.getByText('Concentration risk')).toBeTruthy()
    expect(screen.queryByText(/effective/)).toBeNull()
  })

  it('does not report a green 0.0% concentration when nothing is priced', () => {
    // The one absence in this row that actively reassures: the tone ladder calls
    // anything under 50% good news, so an unpriced portfolio rendered a green "0.0%"
    // claiming the five largest holdings are none of the book — while the effective
    // count that would have qualified it correctly dropped out of the same footnote.
    renderWith({ top5Weight: null, effectiveHoldings: null })
    expect(screen.getByText('No priced positions')).toBeTruthy()
    expect(screen.queryByText('0.0%')).toBeNull()
    expect(screen.queryByText(/Concentration risk/)).toBeNull()
  })

  it('labels a short window a period return instead of annualizing it', () => {
    renderWith({ xirrMethod: 'simple_period' })
    expect(screen.getByText('Period Return')).toBeTruthy()
    expect(screen.queryByText('Annual Return (XIRR)')).toBeNull()
  })

  it('shows a dash, never a zero, for an unresolved return', () => {
    renderWith({ xirr: null, calmarRatio: null })
    expect(screen.queryByText('0.00%')).toBeNull()
    expect(screen.queryByText('0.00')).toBeNull()
  })

  it('says why Sharpe is absent instead of rendering a plausible 0.00', () => {
    // Reachable in one click before this: MTD in the first days of a month leaves 2
    // daily returns, and `sharpeRatio` returned 0 — drawn green, captioned
    // "Risk-adjusted return", beside a dashed Volatility and Sortino. A 0.00 Sharpe is
    // plausible, so nothing about it invited doubt.
    renderWith({ sharpeRatio: null })
    expect(screen.getByText('Not enough history in this range')).toBeTruthy()
    expect(screen.queryByText('0.00')).toBeNull()
  })

  // Not asserting "the absent Sharpe isn't green" here: other cards in this row are
  // legitimately green, so a container-wide query catches them instead. `KpiCard` refuses
  // to colour a `value={null}` regardless of the `tone` passed, and owns that test.

  it('renders nothing at all rather than an empty shell', () => {
    const { container } = render(<PerformanceMetricsCards metrics={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows six loading placeholders, matching the grid it fills', () => {
    const { container } = render(<PerformanceMetricsCards metrics={null} isLoading />)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(6)
  })
})

describe('a backend failure is stated, not silent', () => {
  it('says the backend did not respond instead of rendering nothing', () => {
    const { container } = render(<PerformanceMetricsCards metrics={null} isError />)
    expect(container.firstChild).not.toBeNull()
    expect(screen.getByText(/backend didn't respond/)).toBeTruthy()
  })

  it('still renders nothing when there is simply no data yet', () => {
    const { container } = render(<PerformanceMetricsCards metrics={null} />)
    expect(container.firstChild).toBeNull()
  })
})
