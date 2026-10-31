import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Section({ title, children, className, actions }: { title: string; children: ReactNode; className?: string; actions?: ReactNode }) {
  return (
    <section aria-label={title} className={cn('space-y-2', className)}>
      <div className="flex items-center gap-2">
        <h3 className="flex-1 font-sans text-xs font-semibold uppercase tracking-[0.14em] text-fog">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  )
}

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0', className)}>
      <div className="px-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-fog">{label}</div>
      {children}
    </div>
  )
}
