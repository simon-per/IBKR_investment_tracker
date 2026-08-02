import { useSyncExternalStore } from 'react'
import { COMPACT_QUERY, SIDE_BY_SIDE_QUERY } from './breakpoints'

const NEVER_CHANGES = () => () => {}

/**
 * Reads a media query, and answers `fallback` where `window.matchMedia` does not exist.
 *
 * **The fallback is an invariant, not a default.** jsdom — this repo's component-test
 * environment — implements neither `matchMedia` nor `ResizeObserver` nor
 * `scrollIntoView`. Defaulting to the *desktop* answer means every existing component
 * test keeps rendering the `<table>` it renders today, no vitest setup file is needed,
 * and `e2e/a11y.mjs`'s `th[aria-sort] > 0` keeps passing. Flip it and two component
 * tests plus an e2e check fail on day one. Callers pass `false` only where the desktop
 * answer *is* false.
 *
 * `useSyncExternalStore` rather than `useState` + `useEffect`: an effect-based read
 * paints the desktop variant once and then swaps, which on a phone is a visible flash
 * of a layout that was never meant for it.
 */
export function useMediaQuery(query: string, fallback = true): boolean {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function'

  const subscribe = (onChange: () => void) => {
    if (!supported) return NEVER_CHANGES()
    const mql = window.matchMedia(query)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }

  return useSyncExternalStore(
    subscribe,
    () => (supported ? window.matchMedia(query).matches : fallback),
    // Same answer server-side, so a hydration mismatch is impossible.
    () => fallback,
  )
}

/**
 * True below Tailwind's `sm` — i.e. render the phone layout.
 *
 * Falls back to `false` (desktop) with no `matchMedia`; see above for why that
 * direction is load-bearing.
 */
export function useIsCompact(): boolean {
  return useMediaQuery(COMPACT_QUERY, false)
}

/** True at Tailwind's `lg` and up, where the paired card grids really are side by side. */
export function useIsSideBySide(): boolean {
  return useMediaQuery(SIDE_BY_SIDE_QUERY, true)
}
