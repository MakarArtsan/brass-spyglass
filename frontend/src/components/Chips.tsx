import { cn } from '@/lib/utils'

interface Props<T extends string> {
  options: { value: T; label: string; color?: string }[]
  value: T[]
  onToggle: (value: T) => void
  label: string
}

/** Фильтр-чипы (мультивыбор). Область касания ≥ 44 px, как требует ТЗ. */
export function FilterChips<T extends string>({ options, value, onToggle, label }: Props<T>) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o.value)
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(o.value)}
            className={cn(
              'flex min-h-touch items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors duration-fast',
              on ? 'border-brass bg-brass/15 text-brass-light' : 'border-line text-fog hover:border-fog hover:text-paper',
            )}
          >
            {o.color && <span className="h-2 w-2 rounded-full" style={{ backgroundColor: o.color }} />}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
