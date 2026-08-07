// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { ContributionsStrip } from './ContributionsStrip'
import type { ContributionsResponse, ContributionWindow } from '@/lib/api'

/**
 * The strip renders money in per month; `MonthlyDeploymentCard`, on the same tab, renders
 * an average per month of capital *deployed*. Both are right and they agree wherever they
 * measure the same thing — but each was called "avg monthly", over different windows, with
 * the distinction living only in a `title` attribute. Reported as "they seem to be
 * different from each other", which they were not.
 *
 * So two things have to hold: the label says which quantity it is, and the `/` suffix that
 * pairs money in with deployment carries a legend that survives having no pointer.
 */

afterEach(cleanup)

function win(over: Partial<ContributionWindow> = {}): ContributionWindow {
  return {
    label: 'all',
    months: 26,
    partial: false,
    money_in_eur: 53000,
    avg_money_in_per_month_eur: 2026,
    money_in_method: 'spliced',
    deposits_eur: 17000,
    deployed_eur: 53000,
    avg_deployed_per_month_eur: 2023,
    net_eur: 52000,
    ...over,
  }
}

function data(windows: ContributionWindow[]): ContributionsResponse {
  return {
    windows,
    monthly: [{ month: '2026-07', deployed_eur: 1000, net_eur: 1000 }],
    first_contribution_date: '2024-05-28',
    deposits_from: '2026-01-09',
    coverage_from: '2026-01-09',
    transfer_in_date: '2026-01-19',
    base_currency: 'CHF',
  }
}

describe('ContributionsStrip', () => {
  it('names the quantity it averages', () => {
    render(<ContributionsStrip data={data([win()])} />)
    expect(screen.getByText('Avg Monthly in')).toBeTruthy()
  })

  it('explains the money-in / deployed pair without needing a pointer', () => {
    render(<ContributionsStrip data={data([win()])} />)
    // Both figures are on screen as `2,026` and a `/2,023` suffix; the legend is what makes
    // that readable as two numbers rather than one broken one.
    expect(screen.getByText(/in \/ deployed/)).toBeTruthy()
    expect(screen.getByText(/2,023/)).toBeTruthy()
  })

  it('omits the legend when no suffix is rendered', () => {
    // Under the 'deployed' method money in IS deployment, so the suffix is suppressed and a
    // legend would describe something that is not on screen.
    render(<ContributionsStrip data={data([win({ money_in_method: 'deployed' })])} />)
    expect(screen.getByText('Avg Monthly in')).toBeTruthy()
    expect(screen.queryByText(/in \/ deployed/)).toBeNull()
  })

  it('still says unavailable rather than vanishing on a failed fetch', () => {
    // `e2e/errors.mjs` matches this exact string — a strip that renders nothing is
    // indistinguishable from an account with no contribution history.
    render(<ContributionsStrip data={undefined} isError />)
    expect(screen.getByText(/Avg Monthly unavailable/)).toBeTruthy()
  })
})
