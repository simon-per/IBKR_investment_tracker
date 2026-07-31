import { Component, Suspense, type ReactNode } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'

/**
 * Suspense + a scoped error boundary for a lazily-loaded tab panel.
 *
 * Two reasons this is not just `<Suspense>`:
 *
 * 1. **A lazy chunk can fail to load, and here that is expected rather than exotic.**
 *    The VPS auto-deploys within 10 minutes of any push and the build emits
 *    content-hashed filenames, so a browser that has had the app open across a deploy
 *    holds an `index.html` referencing chunks that no longer exist. Clicking a tab then
 *    404s. Unhandled, that rejection propagates to the app-level boundary in `App.tsx`
 *    and blanks the entire dashboard — a worse outcome than the eager import this
 *    replaced, which could never fail after first paint.
 *
 * 2. **The failure is recoverable and self-explanatory**, so the panel says so and
 *    offers the reload that actually fixes it, instead of showing a generic error. A
 *    plain reload is enough: `frontend-nginx.conf` serves `index.html` with
 *    `Cache-Control: no-cache`, so the next load picks up the new chunk names.
 *
 * Scoped deliberately — a failure in one panel leaves the rest of the app usable, and
 * the tab strip stays operable so the user can move elsewhere.
 */

interface State {
  hasError: boolean
  error: Error | null
}

/** Vite, webpack and Safari each word this differently; all mean the same thing. */
function isChunkLoadError(error: Error | null): boolean {
  if (!error) return false
  const text = `${error.name} ${error.message}`
  return /dynamically imported module|Loading chunk|Importing a module script failed|error loading dynamically imported module/i.test(
    text
  )
}

class LazyTabBoundary extends Component<{ children: ReactNode; label: string }, State> {
  constructor(props: { children: ReactNode; label: string }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const stale = isChunkLoadError(this.state.error)
    return (
      <div
        role="alert"
        className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed py-16 text-center"
      >
        <p className="text-sm font-medium text-foreground">
          {this.props.label} couldn&apos;t load
        </p>
        <p className="max-w-sm text-sm text-muted-foreground">
          {stale
            ? 'A new version of the app was deployed while this page was open, so this section is no longer available at the address the page has. Reloading picks up the new version.'
            : this.state.error?.message || 'An unexpected error occurred.'}
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground ring-offset-background hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Reload
        </button>
      </div>
    )
  }
}

interface LazyTabPanelProps {
  children: ReactNode
  /** Names the section in the loading and error states, e.g. "Watchlist". */
  label: string
}

export function LazyTabPanel({ children, label }: LazyTabPanelProps) {
  return (
    <LazyTabBoundary label={label}>
      <Suspense
        fallback={
          // aria-live so a screen reader announces the wait; the tab strip has already
          // moved selection by the time this renders.
          <div
            className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading {label}…
          </div>
        }
      >
        {children}
      </Suspense>
    </LazyTabBoundary>
  )
}
