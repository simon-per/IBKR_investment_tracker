// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { RiskMetricsCards, type RiskMetrics } from './RiskMetricsCards'

/**
 * Every metric on this row can legitimately be unknown, and each has its own
 * reason. The failure mode these pin is the one the rest of this codebase keeps
 * paying for: an unknown rendered as a number — a `0` volatility for "not
 * enough history", or a beta drawn from a fortnight shown with no qualifier.
 */

afterEach(cleanup)

const base: RiskMetrics = {
  volatilityPct: 18.4,
  sortino: 1.35,
  currentDrawdownPct: -3.21,
  maxDrawdownPct: -12.5,
  troughDate: '2026-04-07',
  recoveredDate: null,
  effectiveHoldings: 12.3,
  totalPositions: 36,
  beta: { beta: 1.08, correlation: 0.87, sampleDays: 64, minSampleDays: 20, benchmarkName: 'S&P 500' },
}

function renderWith(overrides: Partial<RiskMetrics> = {}) {
  return render(<RiskMetricsCards metrics={{ ...base, ...overrides }} />)
}

describe('RiskMetricsCards', () => {
  it('renders every metric when all of them are known', () => {
    renderWith()
    expect(screen.getByText('18.4%')).toBeTruthy()
    expect(screen.getByText('1.35')).toBeTruthy()
    expect(screen.getByText('1.08')).toBeTruthy()
    expect(screen.getByText('-3.21%')).toBeTruthy()
    expect(screen.getByText('12.3')).toBeTruthy()
  })

  it('renders nothing at all rather than an empty shell with no metrics', () => {
    const { container } = render(<RiskMetricsCards metrics={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows a dash, never a zero, for an unknown volatility', () => {
    renderWith({ volatilityPct: null })
    expect(screen.getByText('Not enough history in this range')).toBeTruthy()
    expect(screen.queryByText('0.0%')).toBeNull()
  })

  it('says why Sortino is absent instead of showing a cap', () => {
    renderWith({ sortino: null })
    expect(screen.getByText('No down days to measure against')).toBeTruthy()
  })

  it('asks for a benchmark when none is selected', () => {
    renderWith({ beta: null })
    expect(screen.getByText('Pick a benchmark to compare against')).toBeTruthy()
  })

  it('names the sample shortfall rather than showing a thin beta', () => {
    renderWith({
      beta: { beta: null, correlation: null, sampleDays: 12, minSampleDays: 20, benchmarkName: 'S&P 500' },
    })
    expect(screen.getByText('Needs 20 flow-free days (12 so far)')).toBeTruthy()
  })

  it('credits the benchmark and the correlation beside a beta', () => {
    renderWith()
    expect(screen.getByText('vs S&P 500 · r 0.87')).toBeTruthy()
  })

  it('drops the correlation from the footnote when only beta resolved', () => {
    renderWith({
      beta: { beta: 1.08, correlation: null, sampleDays: 64, minSampleDays: 20, benchmarkName: 'MSCI World' },
    })
    expect(screen.getByText('vs MSCI World')).toBeTruthy()
  })

  it('dates the trough while the drawdown is still open', () => {
    renderWith()
    expect(screen.getByText('Worst -12.5% on 7 Apr')).toBeTruthy()
  })

  it('says it recovered instead of leaving the worst fall reading as live', () => {
    renderWith({ currentDrawdownPct: 0, recoveredDate: '2026-05-19' })
    expect(screen.getByText('Recovered 19 May from -12.5%')).toBeTruthy()
  })

  it('does not invent a drawdown for a portfolio that never fell', () => {
    renderWith({ currentDrawdownPct: 0, maxDrawdownPct: 0, troughDate: null })
    expect(screen.getByText('Never below its opening value')).toBeTruthy()
  })

  it('reports no effective count when nothing is priced', () => {
    renderWith({ effectiveHoldings: null })
    expect(screen.getByText('No priced positions')).toBeTruthy()
  })

  it('shows five loading placeholders, matching the grid it fills', () => {
    const { container } = render(<RiskMetricsCards metrics={null} isLoading />)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(5)
  })
})
