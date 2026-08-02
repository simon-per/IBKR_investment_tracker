/**
 * The two viewport boundaries the app switches layout at, as numbers JS can read.
 *
 * These are not a second set of breakpoints. They are Tailwind's stock `sm` and `lg`,
 * named here because a handful of decisions cannot be expressed as a `sm:` utility —
 * a Recharts `YAxis width` is a prop, and a table becoming a card list is a different
 * DOM tree, not a different class. Everything that *can* stay in CSS does.
 *
 * That makes them exactly the shape of the duplication this codebase keeps getting
 * bitten by: one number, written down twice, in two languages. `breakpoints.test.ts`
 * asserts them against the resolved Tailwind config rather than trusting the comment,
 * so adding a `screens` override to `tailwind.config.js` fails the suite instead of
 * silently splitting the layout in half.
 */

/** Tailwind `sm`. Below this the app renders its phone layout. */
export const COMPACT_MAX_PX = 640

/**
 * Tailwind `lg`. Where the two-column card grids actually become two columns —
 * `FundamentalsTab` measures a sibling card's height and may only do so above this.
 */
export const SIDE_BY_SIDE_MIN_PX = 1024

/**
 * `- 0.02` mirrors how Tailwind itself builds a `max-*` variant, so this query and
 * `sm:` can never both match (or both miss) at a fractional viewport width.
 */
export const COMPACT_QUERY = `(max-width: ${COMPACT_MAX_PX - 0.02}px)`

export const SIDE_BY_SIDE_QUERY = `(min-width: ${SIDE_BY_SIDE_MIN_PX}px)`
