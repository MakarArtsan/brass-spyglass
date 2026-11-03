import { useQuery } from '@tanstack/react-query'
import { api, type SessionInfo } from '@/lib/api'
import { currentSlug, openProject } from '@/lib/project'
import { sessionKey } from '@/hooks/useAuth'
import { ru } from '@/ru'

/** Переключатель проектов: виден, только если человеку открыто больше одного. Переход — обычная
 * загрузка адреса нового проекта, поэтому от прежнего проекта на странице ничего не остаётся. */
export function ProjectSwitcher() {
  const { data } = useQuery({ queryKey: sessionKey, queryFn: () => api<SessionInfo>('/session'), staleTime: 60_000 })
  const projects = data?.projects ?? []
  if (projects.length < 2) return null
  return (
    <label className="flex flex-col gap-1 px-3 pt-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-fog/70">
      {ru.projects.switcher}
      <select
        value={currentSlug ?? ''}
        onChange={(e) => openProject(e.target.value)}
        className="min-h-touch rounded-lg border border-line bg-ink px-2 text-sm font-medium normal-case tracking-normal text-paper"
      >
        {projects.map((p) => (
          <option key={p.slug} value={p.slug}>
            {p.title}
            {p.archived ? ` (${ru.projects.archived})` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}
