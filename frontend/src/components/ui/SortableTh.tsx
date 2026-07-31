import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export type SortDirection = 'asc' | 'desc'

interface SortableThProps<T extends string> {
  column: T
  label: React.ReactNode
  activeColumn: T | null | undefined
  direction: SortDirection
  onSort: (column: T) => void
  align?: 'left' | 'right' | 'center'
  /** Native tooltip on the header cell — several tables define their metric here. */
  title?: string
  /** Classes for the `<th>`; the inner button owns its own layout. */
  className?: string
  /** Icon size. The wide tables run 3, the roomier ones 4. */
  iconClassName?: string
  /** Extra handlers on the `<th>`, e.g. a hover/focus tooltip. */
  onMouseEnter?: React.MouseEventHandler<HTMLTableCellElement>
  onMouseLeave?: React.MouseEventHandler<HTMLTableCellElement>
  onFocus?: React.FocusEventHandler<HTMLTableCellElement>
  onBlur?: React.FocusEventHandler<HTMLTableCellElement>
}

const ALIGN_TH = { left: 'text-left', right: 'text-right', center: 'text-center' } as const
const ALIGN_BUTTON = { left: 'justify-start', right: 'justify-end', center: 'justify-center' } as const

/**
 * A sortable table header.
 *
 * `PositionsList` already did this correctly — a real `<button>` inside the `<th>` —
 * while `FundamentalsTab` and `WatchlistTab` put `onClick` straight on the `<th>`, so
 * their columns could not be sorted without a mouse. This is that working pattern
 * lifted out, plus `aria-sort`, which none of the three had: without it a screen
 * reader announces a column header with no indication that the table is sorted by it
 * or in which direction, and the arrow glyph is decorative.
 */
export function SortableTh<T extends string>({
  column,
  label,
  activeColumn,
  direction,
  onSort,
  align = 'left',
  title,
  className,
  iconClassName = 'h-4 w-4',
  ...thHandlers
}: SortableThProps<T>) {
  const isActive = activeColumn === column

  return (
    <th
      // The live sort state, for anything that isn't looking at the arrow.
      aria-sort={isActive ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={cn('font-medium', ALIGN_TH[align], className)}
      title={title}
      {...thHandlers}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        className={cn(
          'flex w-full items-center gap-1 rounded-sm ring-offset-background transition-colors hover:text-foreground',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
          ALIGN_BUTTON[align],
          isActive && 'text-foreground'
        )}
      >
        <span>{label}</span>
        {isActive ? (
          direction === 'asc' ? (
            <ArrowUp aria-hidden="true" className={iconClassName} />
          ) : (
            <ArrowDown aria-hidden="true" className={iconClassName} />
          )
        ) : (
          <ArrowUpDown aria-hidden="true" className={cn(iconClassName, 'opacity-30')} />
        )}
      </button>
    </th>
  )
}
