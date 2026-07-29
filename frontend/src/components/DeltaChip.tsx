import { cn } from '@/lib/utils'
import { deltaArrow, deltaColor, formatDelta } from '@/lib/delta'

interface DeltaChipProps {
  /** null renders a dash: the backend says there was no base to grow from. */
  pct: number | null | undefined
  /** What the percentage is measured against, e.g. "vs 2025". */
  label?: string
  /**
   * Marks the figure as forward-looking. A forecast compared against measured
   * income is a legitimate number but not the same kind of number, and the two
   * must not sit side by side looking identical.
   */
  projected?: boolean
  /**
   * Marks the comparison as unreliable even though the arithmetic is right —
   * a coverage-limited prior period, or one sourced differently. Shown as a
   * trailing marker with the reason in the title.
   */
  caveat?: string
  title?: string
  className?: string
}

/**
 * Signed percentage with a direction arrow, in the app's existing delta colours.
 *
 * Deliberately quiet: inside the flat band there is no arrow and no colour,
 * because dividend income is lumpy enough that a few percent is noise.
 */
export function DeltaChip({
  pct, label, projected, caveat, title, className,
}: DeltaChipProps) {
  const arrow = deltaArrow(pct)
  const hasValue = pct != null && Number.isFinite(pct)

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-xs tabular-nums',
        hasValue ? deltaColor(pct) : 'text-muted-foreground',
        className,
      )}
      title={title}
    >
      {arrow && <span aria-hidden="true">{arrow}</span>}
      <span className="font-medium">{formatDelta(pct)}</span>
      {label && <span className="font-normal text-muted-foreground">{label}</span>}
      {/* After the label, not before it: "+81.8% est. vs last 12M" reads as a
          stumble, "+81.8% vs last 12M · est." reads as an annotation. */}
      {projected && hasValue && (
        <span className="font-normal text-muted-foreground" title="Projected, not measured">
          · est.
        </span>
      )}
      {/* A dagger, not "!" — an exclamation mark beside a percentage looks like
          emphasis or a typo rather than a caveat, and "*" is already taken twice
          on this tab (gross estimate, incomplete year). */}
      {caveat && hasValue && (
        <span className="text-amber-600 dark:text-amber-500" title={caveat} aria-label={caveat}>
          †
        </span>
      )}
    </span>
  )
}
