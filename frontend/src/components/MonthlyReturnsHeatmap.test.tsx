// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MonthlyReturnsHeatmap } from './MonthlyReturnsHeatmap'
import type { PortfolioValuePoint } from '@/lib/api'

/**
 * The card is collapsed by default, so its one-line summary is the only thing most
 * readers ever see — and it rendered the figure with no partial marker while the table
 * inside badged the same figure with a dagger and explained it in a footnote.
 *
 * That is how a "YTD" measured over six weeks of a year read as an answer: one unpriceable
 * holding (a spinoff whose tax lots predate its listing) made every day from November to
 * June unmeasurable, `computeModifiedDietzReturn` trimmed the window to the days it could
 * use, and the collapsed line showed +3.1% flat.
 */

afterEach(cleanup)

function point(date: string, mv: number, unpriced = 0): PortfolioValuePoint {
  return {
    date,
    cost_basis_eur: 900,
    market_value_eur: mv,
    gain_loss_eur: mv - 900,
    gain_loss_percent: 0,
    external_flow_eur: 0,
    unpriced_holdings: unpriced,
  }
}

describe('MonthlyReturnsHeatmap', () => {
  it('carries the partial marker into the collapsed summary', () => {
    // February is fine; March's last day cannot be valued, so the YTD figure and the
    // March figure both stop short of the period they are labelled with.
    render(
      <MonthlyReturnsHeatmap
        isLoading={false}
        data={[
          point('2026-02-02', 1000),
          point('2026-02-27', 1010),
          point('2026-03-02', 1010),
          point('2026-03-30', 1030),
          point('2026-03-31', 400, 2),
        ]}
      />
    )
    // Still collapsed: no table yet, so the footnote explaining the dagger is not rendered
    // either — which is why the summary spells the caveat out in words.
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByText(/part of the period only/)).toBeTruthy()
  })

  it('leaves the summary unqualified when every period is complete', () => {
    render(
      <MonthlyReturnsHeatmap
        isLoading={false}
        data={[
          point('2026-03-02', 1000),
          point('2026-03-31', 1050),
        ]}
      />
    )
    expect(screen.queryByText(/part of the period only/)).toBeNull()
    expect(screen.getByText(/Mar:/)).toBeTruthy()
  })

  it('says the request failed rather than claiming there is not enough data', () => {
    render(<MonthlyReturnsHeatmap isLoading={false} isError data={undefined} />)
    expect(screen.getByText(/Could not load the value history/)).toBeTruthy()
  })
})
