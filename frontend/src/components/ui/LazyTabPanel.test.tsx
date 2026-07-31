// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest'
import { lazy } from 'react'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { LazyTabPanel } from './LazyTabPanel'

/**
 * The seven non-default tabs are `React.lazy`, so their code arrives over the network
 * after first paint. That introduces a failure the eager imports could not have: the VPS
 * redeploys within 10 minutes of any push and chunks are content-hashed, so a browser
 * holding the page across a deploy asks for a filename that no longer exists.
 *
 * Unhandled, that rejection reaches the app-level boundary in `App.tsx` and blanks the
 * whole dashboard — strictly worse than before the split. These pin the scoped recovery.
 */

afterEach(cleanup)

beforeEach(() => {
  // The boundary logs through React's own error reporting; silence it so a deliberate
  // throw does not look like a failing test.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

function Boom({ error }: { error: Error }): React.ReactElement {
  throw error
}

describe('LazyTabPanel', () => {
  it('renders its children when nothing goes wrong', () => {
    render(
      <LazyTabPanel label="Watchlist">
        <p>Panel body</p>
      </LazyTabPanel>
    )
    expect(screen.getByText('Panel body')).toBeTruthy()
  })

  it('explains a stale deploy rather than showing a raw chunk error', () => {
    // Vite's exact wording when a hashed chunk 404s after a redeploy.
    const err = new Error(
      'Failed to fetch dynamically imported module: https://example.com/assets/TaxTab-a1b2c3.js'
    )
    render(
      <LazyTabPanel label="Tax">
        <Boom error={err} />
      </LazyTabPanel>
    )

    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText(/Tax couldn't load/)).toBeTruthy()
    expect(screen.getByText(/new version of the app was deployed/i)).toBeTruthy()
    // The URL is noise to the user and would be the only thing a generic handler showed.
    expect(screen.queryByText(/TaxTab-a1b2c3\.js/)).toBeNull()
  })

  it('recognises the other wordings the same failure ships under', () => {
    // Safari and webpack phrase it differently; all three mean a missing chunk.
    for (const message of [
      'Importing a module script failed.',
      'Loading chunk 42 failed.',
      'error loading dynamically imported module',
    ]) {
      render(
        <LazyTabPanel label="Forecast">
          <Boom error={new Error(message)} />
        </LazyTabPanel>
      )
      expect(screen.getByText(/new version of the app was deployed/i)).toBeTruthy()
      cleanup()
    }
  })

  it('shows a real error message when the failure is not a missing chunk', () => {
    render(
      <LazyTabPanel label="Allocation">
        <Boom error={new Error('Cannot read properties of undefined')} />
      </LazyTabPanel>
    )
    // A genuine bug must not be mislabelled as a deploy race, or it gets "fixed" by
    // reloading forever.
    expect(screen.getByText('Cannot read properties of undefined')).toBeTruthy()
    expect(screen.queryByText(/new version of the app was deployed/i)).toBeNull()
  })

  it('offers a reload, which is what actually recovers a stale chunk', async () => {
    const reload = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, reload },
      writable: true,
    })

    render(
      <LazyTabPanel label="Tax">
        <Boom error={new Error('Failed to fetch dynamically imported module')} />
      </LazyTabPanel>
    )
    screen.getByRole('button', { name: /reload/i }).click()
    expect(reload).toHaveBeenCalled()
  })

  it('names the section while the chunk is still in flight', async () => {
    let resolve!: (m: { default: () => React.ReactElement }) => void
    const Pending = lazy(() => new Promise<{ default: () => React.ReactElement }>(r => { resolve = r }))

    render(
      <LazyTabPanel label="Dividends">
        <Pending />
      </LazyTabPanel>
    )
    // "Loading…" alone gives no clue which of eight tabs is waiting.
    expect(screen.getByText(/Loading Dividends/)).toBeTruthy()

    resolve({ default: () => <p>Arrived</p> })
    await waitFor(() => expect(screen.getByText('Arrived')).toBeTruthy())
  })
})
