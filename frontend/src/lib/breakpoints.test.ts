import { describe, expect, it } from 'vitest'
import defaultTheme from 'tailwindcss/defaultTheme'
// `?raw` rather than `node:fs`: tsconfig.app.json restricts `types` to `vite/client`
// so that browser code cannot reach Node globals, and Vite already declares this form.
import tailwindConfigSource from '../../tailwind.config.js?raw'
import {
  COMPACT_MAX_PX,
  COMPACT_QUERY,
  SIDE_BY_SIDE_MIN_PX,
  SIDE_BY_SIDE_QUERY,
} from './breakpoints'

/**
 * The mobile layout is decided in two languages: `sm:` utilities in the markup and
 * these constants in the JS that sizes chart axes and swaps a table for a card list.
 * They describe one boundary, so they have to agree — and nothing in the type system
 * or the build makes them.
 *
 * That is the exact shape of this repo's documented dominant failure mode, so it gets
 * a test rather than a comment: both copies are read from source and compared.
 */
describe('the JS breakpoints and Tailwind cannot disagree', () => {
  it('matches Tailwind\'s stock sm and lg', () => {
    expect(defaultTheme.screens?.sm).toBe(`${COMPACT_MAX_PX}px`)
    expect(defaultTheme.screens?.lg).toBe(`${SIDE_BY_SIDE_MIN_PX}px`)
  })

  it('has no screens override in tailwind.config.js', () => {
    // Scanned as source rather than imported: the config is plain JS with no types,
    // and a text scan catches a `screens` key wherever it is written — under `theme`,
    // under `theme.extend`, or spread in from elsewhere. If one is ever added, these
    // constants stop describing the `sm:` utilities and the two halves of every
    // responsive decision split silently. Move them together.
    expect(tailwindConfigSource).not.toMatch(/\bscreens\b/)
  })

  it('builds max-width queries the way Tailwind does, so neither can straddle a fraction', () => {
    expect(COMPACT_QUERY).toBe('(max-width: 639.98px)')
    expect(SIDE_BY_SIDE_QUERY).toBe('(min-width: 1024px)')
  })
})
