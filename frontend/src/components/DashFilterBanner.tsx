import { X } from 'lucide-react'
import type { DashFilter } from '@/hooks/useDashFilter'
import { ru } from '@/ru'

/** Напоминает, что список отфильтрован плиткой дашборда, и снимает фильтр одним нажатием. */
export function DashFilterBanner({ filter }: { filter: DashFilter }) {
  if (!filter.active) return null
  return (
    <div role="status" className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-brass/40 bg-brass/10 px-3 py-1.5 text-sm">
      <span>
        <span className="text-fog">{ru.dash.activeFilter}: </span>
        <span className="font-medium">{filter.labels.join(' · ')}</span>
      </span>
      <button
        type="button"
        onClick={filter.clear}
        className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-lg px-2 text-brass hover:text-brass-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass"
        aria-label={ru.dash.clearFilter}
      >
        <X size={16} aria-hidden />
        <span className="hidden sm:inline">{ru.dash.clearFilter}</span>
      </button>
    </div>
  )
}
