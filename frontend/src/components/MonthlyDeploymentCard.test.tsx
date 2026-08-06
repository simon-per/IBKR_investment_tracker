// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MonthlyDeploymentCard } from './MonthlyDeploymentCard'
import type { ContributionsResponse, ContributionWindow, ContributionMonthlyItem } from '@/lib/api'

/**
 * This card's collapsed summary sits on the same tab as `ContributionsStrip`, which
 * renders the server's `avg_deployed_per_month_eur`. The card used to recompute the
 * same quantity from `monthly` — one name, two computations, one screen.
 *
 * The recomputation was wrong in a way its own shape hid: `monthly` only contains
 * months that had activity, so `slice(-12)` takes the last twelve *rows* (which can
 * span more than twelve months) and divides by that row count rather than by the
 * months covered. Both errors push the average up.
 */

afterEach(cleanup)

function win(over: Partial<ContributionWindow> = {}): ContributionWindow {
  return {
    label: '12m',
    months: 12,
    partial: false,
    money_in_eur: 24000,
    avg_money_in_per_month_eur: 2000,
    money_in_method: 'spliced',
    deposits_eur: 24000,
    deployed_eur: 30000,
    avg_deployed_per_month_eur: 2500,
    net_eur: 28000,
    ...over,
  }
}

function month(m: string, deployed: number): ContributionMonthlyItem {
  return { month: m, deployed_eur: deployed, net_eur: deployed }
}

function data(over: Partial<ContributionsResponse> = {}): ContributionsResponse {
  return {
    windows: [win()],
    monthly: [month('2026-06', 1000), month('2026-07', 9999)],
    first_contribution_date: '2024-05-01',
    deposits_from: '2026-01-09',
    coverage_from: '2026-01-09',
    transfer_in_date: '2026-01-20',
    base_currency: 'EUR',
    ...over,
  }
}

describe('the 12M average comes from the server, not from a second computation', () => {
  it("shows the server's average rather than one derived from the monthly rows", () => {
    // The rows average 5,499.50; the server says 2,500. Only the server's may appear.
    render(<MonthlyDeploymentCard data={data()} isLoading={false} />)
    expect(screen.getByText(/12M avg/)).toBeTruthy()
    expect(screen.getByText(/2,500\/mo/)).toBeTruthy()
    expect(screen.queryByText(/5,50[01]|5,499/)).toBeNull()
  })

  it('is immune to a month with no activity being absent from the rows', () => {
    // A gap makes `slice(-12)` span more calendar months than it divides by. Reading
    // the server's figure means the rows cannot influence the average at all.
    render(
      <MonthlyDeploymentCard
        data={data({ monthly: [month('2026-01', 50000), month('2026-07', 50000)] })}
        isLoading={false}
      />,
    )
    expect(screen.getByText(/2,500\/mo/)).toBeTruthy()
  })

  it('names the window it actually measured when history is short', () => {
    // A four-month-old portfolio has no twelve-month average. The server already
    // clamps the divisor; the label must not still claim twelve.
    render(
      <MonthlyDeploymentCard
        data={data({ windows: [win({ partial: true, months: 4, avg_deployed_per_month_eur: 900 })] })}
        isLoading={false}
      />,
    )
    expect(screen.getByText(/4M avg/)).toBeTruthy()
    expect(screen.queryByText(/12M avg/)).toBeNull()
  })

  it('still reports the latest month when the server sends no 12m window', () => {
    render(<MonthlyDeploymentCard data={data({ windows: [] })} isLoading={false} />)
    expect(screen.getByText(/9,999 deployed/)).toBeTruthy()
    expect(screen.queryByText(/avg/)).toBeNull()
  })

  it('states a failure rather than reporting no capital deployed', () => {
    render(<MonthlyDeploymentCard data={undefined} isLoading={false} isError />)
    expect(screen.getByText(/Could not load contributions/)).toBeTruthy()
  })
})
