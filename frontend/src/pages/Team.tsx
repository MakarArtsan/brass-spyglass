import { Avatar } from '@/components/Avatar'
import { useUsers } from '@/hooks/useAuth'
import { ru } from '@/ru'

const fmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export default function Team() {
  const { data: users } = useUsers()
  return (
    <section>
      <h1 className="text-4xl">{ru.team.title}</h1>
      <p className="mt-1 text-fog">{ru.team.lead}</p>
      <ul className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {users?.map((u) => (
          <li key={u.id} className="panel flex items-center gap-4 p-4">
            <Avatar user={u} className="h-12 w-12 text-sm" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{u.name}</div>
              <div className="truncate text-xs text-fog">{u.tg_username ? `@${u.tg_username}` : '—'}</div>
              <div className="mt-1 text-xs text-fog">
                {ru.team.lastSeen}: {u.last_seen_at ? fmt.format(new Date(u.last_seen_at)) : ru.team.never}
              </div>
            </div>
            <span className="rounded-full border border-brass/40 px-2.5 py-0.5 text-xs font-semibold text-brass">{ru.roles[u.role]}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
