import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'

const MAX_BENCHMARKS = 3

export const BENCHMARK_COLORS = [
  '#3b82f6', // blue
  '#ec4899', // pink
  '#f97316', // orange
  '#06b6d4', // cyan
  '#a855f7', // purple
  '#14b8a6', // teal
  '#ef4444', // red
  '#84cc16', // lime
]

interface BenchmarkPickerProps {
  selected: string[]
  onChange: (keys: string[]) => void
}

export function BenchmarkPicker({ selected, onChange }: BenchmarkPickerProps) {
  const { data: benchmarks } = useQuery({
    queryKey: ['portfolio', 'benchmarks'],
    queryFn: () => api.getAvailableBenchmarks(),
    staleTime: Infinity,
  })

  const toggle = (key: string) => {
    if (selected.includes(key)) {
      onChange(selected.filter(k => k !== key))
    } else if (selected.length < MAX_BENCHMARKS) {
      onChange([...selected, key])
    }
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 w-8 p-0">
          <Plus className="h-4 w-4" />
          <span className="sr-only">Add benchmark</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-2">
        <div className="text-xs font-medium text-muted-foreground px-2 py-1.5">
          Compare with (max {MAX_BENCHMARKS})
        </div>
        {benchmarks?.map((b) => {
          const isSelected = selected.includes(b.key)
          const colorIndex = isSelected ? selected.indexOf(b.key) : 0
          const disabled = !isSelected && selected.length >= MAX_BENCHMARKS

          return (
            <button
              key={b.key}
              onClick={() => toggle(b.key)}
              disabled={disabled}
              className={`w-full flex items-center gap-2 text-sm px-2 py-1.5 rounded-md transition-colors text-left ${
                disabled
                  ? 'text-muted-foreground/50 cursor-not-allowed'
                  : 'hover:bg-muted/50'
              }`}
            >
              <div
                className="w-3 h-3 rounded-sm border flex-shrink-0"
                style={{
                  backgroundColor: isSelected ? BENCHMARK_COLORS[colorIndex] : 'transparent',
                  borderColor: isSelected ? BENCHMARK_COLORS[colorIndex] : 'hsl(var(--border))',
                }}
              />
              <span className="flex-1">{b.name}</span>
              <span className="text-xs text-muted-foreground">{b.currency}</span>
            </button>
          )
        })}
      </PopoverContent>
    </Popover>
  )
}
