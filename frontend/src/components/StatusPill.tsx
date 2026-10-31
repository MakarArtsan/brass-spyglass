import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { Check } from 'lucide-react'
import { STATUS_ORDER } from '@/brand'
import { StatusChip } from '@/components/StatusChip'
import { cn } from '@/lib/utils'
import type { StatusKey } from '@/lib/types'
import { ru } from '@/ru'

interface Props {
  status: StatusKey
  /** Без обработчика — просто цветной чип. */
  onChange?: (status: StatusKey) => void
  className?: string
}

/** Статус цветом из Excel-трекера; по клику открывается список из шести статусов. */
export function StatusPill({ status, onChange, className }: Props) {
  if (!onChange) return <StatusChip status={status} className={className} />
  return (
    <Dropdown.Root>
      <Dropdown.Trigger
        aria-label={`${ru.shots.status}: ${ru.status[status]}`}
        className={cn(
          'inline-flex rounded-full transition-opacity duration-fast hover:opacity-80 max-lg:min-h-touch max-lg:items-center',
          className,
        )}
      >
        <StatusChip status={status} />
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="start"
          sideOffset={4}
          collisionPadding={12}
          className="z-[80] min-w-[190px] rounded-xl border border-line bg-chart p-1 shadow-xl shadow-black/50"
        >
          {STATUS_ORDER.map((s) => (
            <Dropdown.Item
              key={s}
              onSelect={() => s !== status && onChange(s)}
              className="flex min-h-touch cursor-pointer items-center gap-3 rounded-lg px-3 text-sm outline-none data-[highlighted]:bg-ink"
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: `rgb(var(--status-${s}))` }} />
              <span className={cn('flex-1', s === 'cut' && 'line-through')}>{ru.status[s]}</span>
              {s === status && <Check size={16} className="text-brass" />}
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  )
}
