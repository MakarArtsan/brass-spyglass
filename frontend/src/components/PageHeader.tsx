import type { ReactNode } from 'react'

export function PageHeader({ title, lead, actions }: { title: string; lead?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1">
        <h1 className="text-4xl">{title}</h1>
        {lead && <p className="mt-1 max-w-2xl text-sm text-fog max-lg:hidden">{lead}</p>}
      </div>
      {actions}
    </div>
  )
}
