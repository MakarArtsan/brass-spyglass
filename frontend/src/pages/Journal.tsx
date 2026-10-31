import { Navigate } from 'react-router-dom'
import { useState } from 'react'
import { Avatar } from '@/components/Avatar'
import { PageHeader } from '@/components/PageHeader'
import { useUsers } from '@/hooks/useAuth'
import { usePerms } from '@/hooks/usePerms'
import { describe } from '@/lib/activity'
import { formatDateTime } from '@/lib/format'
import { useActivity } from '@/lib/queries'
import { ru } from '@/ru'

const KINDS = ['scene', 'shot', 'asset', 'asset_state', 'setup_payoff', 'sound_cue', 'task', 'file', 'comment', 'user', 'project'] as const

/** Журнал: кто и что менял. Гостю недоступен — сервер отвечает 403, и интерфейс не показывает раздел. */
export default function Journal() {
  const perms = usePerms()
  const { data: users } = useUsers()
  const [actorId, setActorId] = useState(0)
  const [entityType, setEntityType] = useState('')
  const filter = { actor_id: actorId || undefined, entity_type: entityType || undefined }
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useActivity(filter, perms.canJournal)

  if (perms.role && !perms.canJournal) return <Navigate to="/" replace />
  const items = data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div>
      <PageHeader title={ru.journal.title} lead={ru.journal.lead} />
      <div className="mb-4 flex flex-wrap gap-3">
        <select value={actorId} onChange={(e) => setActorId(Number(e.target.value))} aria-label={ru.journal.actor} className="min-h-touch rounded-lg border border-line bg-chart px-3 text-sm">
          <option value={0}>
            {ru.journal.actor}: {ru.journal.anyone}
          </option>
          {users?.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </select>
        <select value={entityType} onChange={(e) => setEntityType(e.target.value)} aria-label={ru.journal.allKinds} className="min-h-touch rounded-lg border border-line bg-chart px-3 text-sm">
          <option value="">{ru.journal.allKinds}</option>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {ru.journal.entity[k]}
            </option>
          ))}
        </select>
      </div>

      {data && items.length === 0 && <p className="py-12 text-center text-fog">{ru.journal.nothing}</p>}
      <ul className="divide-y divide-line rounded-xl border border-line bg-chart">
        {items.map((item) => {
          const { kind, details } = describe(item)
          return (
            <li key={item.id} data-activity={item.action} className="flex gap-3 p-3">
              {item.actor ? <Avatar user={item.actor} className="h-8 w-8" /> : <span className="h-8 w-8 shrink-0 rounded-full bg-line" />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="font-semibold">{item.actor?.name ?? ru.journal.system}</span>
                  <span className="rounded-full border border-line px-2 py-0.5 text-[11px] text-fog">{kind}</span>
                  <span className="text-brass-light">{item.label ?? (ru.journal.entity as Record<string, string>)[item.entity_type]}</span>
                  <span className="mono ml-auto text-xs text-fog">{formatDateTime(item.at)}</span>
                </div>
                {details.map((d) => (
                  <div key={d} className="mt-0.5 break-words text-sm text-fog">
                    {d}
                  </div>
                ))}
              </div>
            </li>
          )
        })}
      </ul>
      {hasNextPage && (
        <button type="button" onClick={() => fetchNextPage()} disabled={isFetchingNextPage} className="mt-4 min-h-touch w-full rounded-lg border border-line text-sm text-brass hover:border-brass">
          {ru.common.more}
        </button>
      )}
    </div>
  )
}
