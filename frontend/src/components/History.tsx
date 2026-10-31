import { Avatar } from '@/components/Avatar'
import { usePerms } from '@/hooks/usePerms'
import { describe } from '@/lib/activity'
import { formatDateTime } from '@/lib/format'
import { useActivity } from '@/lib/queries'
import { ru } from '@/ru'

/** История карточки из журнала. Гостю журнал не показывается — секции для него нет. */
export function History({ entityType, entityId }: { entityType: string; entityId: number }) {
  const perms = usePerms()
  const { data, fetchNextPage, hasNextPage } = useActivity({ entity_type: entityType, entity_id: entityId }, perms.canJournal)
  if (!perms.canJournal) return null
  const items = data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section aria-label={ru.history.title} className="space-y-3">
      <h3 className="font-sans text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.history.title}</h3>
      {items.length === 0 && <p className="text-sm text-fog">{ru.history.empty}</p>}
      <ul className="space-y-2.5">
        {items.map((item) => {
          const { kind, details } = describe(item)
          return (
            <li key={item.id} className="flex gap-3 text-sm">
              {item.actor ? <Avatar user={item.actor} className="h-6 w-6 text-[10px]" /> : <span className="h-6 w-6 shrink-0 rounded-full bg-line" />}
              <div className="min-w-0 flex-1">
                <div className="text-xs text-fog">
                  <span className="font-semibold text-paper">{item.actor?.name ?? ru.journal.system}</span> · {kind} · {formatDateTime(item.at)}
                </div>
                {details.map((d) => (
                  <div key={d} className="break-words text-sm">
                    {d}
                  </div>
                ))}
              </div>
            </li>
          )
        })}
      </ul>
      {hasNextPage && (
        <button type="button" onClick={() => fetchNextPage()} className="min-h-touch text-sm text-brass hover:text-brass-light">
          {ru.common.more}
        </button>
      )}
    </section>
  )
}
