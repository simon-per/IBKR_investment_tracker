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

  it('renders nothing at all rather than an empty shell', () => {
    const { container } = render(<PerformanceMetricsCards metrics={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows six loading placeholders, matching the grid it fills', () => {
    const { container } = render(<PerformanceMetricsCards metrics={null} isLoading />)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(6)
  })
})
