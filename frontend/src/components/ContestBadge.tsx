import { CONTEST_BADGE } from '@/brand'
import { cn } from '@/lib/utils'

/** Текстовый бейдж конкурса. Логотипы — только после сверки с брендгайдом. */
export function ContestBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'mono inline-flex items-center gap-2 rounded-full border border-brass/40 px-3 py-1 text-[11px] uppercase tracking-[0.14em] text-brass',
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-brass" aria-hidden />
      {CONTEST_BADGE}
    </span>
  )
}
