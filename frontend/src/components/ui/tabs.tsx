import * as React from "react"

/**
 * A minimal tabs primitive.
 *
 * It had no ARIA at all — no `role`, no `aria-selected`, no `tabpanel` association —
 * so assistive technology saw seven unrelated buttons above a `<div>` and nothing tied
 * the two together. Keyboard users also had to Tab through every trigger to reach the
 * last one, where the WAI-ARIA tabs pattern puts the whole list on a single tab stop
 * and moves between triggers with the arrow keys.
 *
 * Both are fixed here rather than by adopting Radix: `@radix-ui/react-tabs` is not a
 * dependency, and adding one to a working primitive this small is a bigger change than
 * the gap warrants.
 */

interface TabsProps {
  defaultValue: string
  children: React.ReactNode
  className?: string
}

interface TabsContextValue {
  value: string
  setValue: (value: string) => void
  baseId: string
}

const TabsContext = React.createContext<TabsContextValue | undefined>(undefined)

function useTabsContext(component: string): TabsContextValue {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error(`${component} must be used within Tabs`)
  return context
}

export function Tabs({ defaultValue, children, className }: TabsProps) {
  const [value, setValue] = React.useState(defaultValue)
  // Per-instance prefix, so two Tabs on one page cannot collide on element ids.
  const baseId = React.useId()

  const context = React.useMemo(() => ({ value, setValue, baseId }), [value, baseId])

  return (
    <TabsContext.Provider value={context}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  )
}

interface TabsListProps {
  children: React.ReactNode
  className?: string
  /** Names the tab list for screen readers. */
  label?: string
}

export function TabsList({ children, className, label = 'Sections' }: TabsListProps) {
  const { setValue } = useTabsContext('TabsList')
  const ref = React.useRef<HTMLDivElement>(null)

  /**
   * Arrow keys move selection, Home/End jump to the ends, and both wrap.
   *
   * Trigger order comes from the DOM rather than a registration list: the DOM is the
   * order the user sees, it needs no bookkeeping to stay in sync, and a registration
   * array re-ordered by an unmount/remount would silently scramble the navigation.
   */
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const keys = ['ArrowRight', 'ArrowLeft', 'Home', 'End']
    if (!keys.includes(e.key)) return

    const triggers = Array.from(
      ref.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]:not([disabled])') ?? []
    )
    if (triggers.length === 0) return

    const current = triggers.findIndex(t => t.getAttribute('aria-selected') === 'true')
    if (current === -1) return

    const next =
      e.key === 'ArrowRight' ? (current + 1) % triggers.length
      : e.key === 'ArrowLeft' ? (current - 1 + triggers.length) % triggers.length
      : e.key === 'Home' ? 0
      : triggers.length - 1

    e.preventDefault()
    const target = triggers[next]
    // Selection follows focus, the WAI-ARIA default for panels cheap to render.
    // Focus has to move too, or the roving tabIndex strands the user on a -1 element.
    setValue(target.dataset.tabValue ?? '')
    target.focus()
  }

  return (
    <div
      ref={ref}
      role="tablist"
      aria-label={label}
      aria-orientation="horizontal"
      onKeyDown={onKeyDown}
      className={`inline-flex h-10 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground ${className || ''}`}
    >
      {children}
    </div>
  )
}

interface TabsTriggerProps {
  value: string
  children: React.ReactNode
  className?: string
}

export function TabsTrigger({ value, children, className }: TabsTriggerProps) {
  const { value: selected, setValue, baseId } = useTabsContext('TabsTrigger')
  const isActive = selected === value

  return (
    <button
      type="button"
      role="tab"
      id={`${baseId}-trigger-${value}`}
      data-tab-value={value}
      aria-selected={isActive}
      aria-controls={`${baseId}-panel-${value}`}
      // Roving tabIndex: the list is one tab stop and arrows move within it.
      tabIndex={isActive ? 0 : -1}
      onClick={() => setValue(value)}
      className={`inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 ${
        isActive
          ? 'bg-background text-foreground shadow-sm'
          : 'hover:bg-background/50'
      } ${className || ''}`}
    >
      {children}
    </button>
  )
}

interface TabsContentProps {
  value: string
  children: React.ReactNode
  className?: string
  forceMount?: boolean
}

export function TabsContent({ value, children, className, forceMount }: TabsContentProps) {
  const { value: selected, baseId } = useTabsContext('TabsContent')
  const isActive = selected === value

  if (!forceMount && !isActive) return null

  return (
    <div
      role="tabpanel"
      id={`${baseId}-panel-${value}`}
      aria-labelledby={`${baseId}-trigger-${value}`}
      // Focusable so Tab out of the trigger list lands on the content it selected,
      // which is what makes a keyboard-only pass through the app read in order.
      tabIndex={isActive ? 0 : -1}
      hidden={forceMount && !isActive}
      className={`mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${className || ''} ${forceMount && !isActive ? 'hidden' : ''}`}
    >
      {children}
    </div>
  )
}
