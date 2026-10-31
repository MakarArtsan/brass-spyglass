import { cn } from '@/lib/utils'
import { ru } from '@/ru'
import type { StatusKey } from '@/brand'

interface Props {
  status: StatusKey
  className?: string
}

/** Статус цветом из Excel-трекера; «Вырезано» — серый и зачёркнутый. */
export function StatusChip({ status, className }: Props) {
  return (
    <span
      className={cn(
        'inline-flex min-h-[28px] items-center gap-1.5 rounded-full border px-3 text-xs font-semibold',
        status === 'cut' && 'line-through',
        className,
      )}
      style={{
        borderColor: `rgb(var(--status-${status}) / 0.5)`,
        backgroundColor: `rgb(var(--status-${status}) / 0.12)`,
      }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: `rgb(var(--status-${status}))` }} />
      {ru.status[status]}
    </span>
  )
}
