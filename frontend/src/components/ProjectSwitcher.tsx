import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { api, type SessionInfo } from '@/lib/api'
import { currentSlug, openProject } from '@/lib/project'
import { sessionKey } from '@/hooks/useAuth'
import { ru } from '@/ru'

/** Переключатель проектов: виден, только если человеку открыто больше одного. Переход — обычная
 * загрузка адреса нового проекта, поэтому от прежнего проекта на странице ничего не остаётся. */
export function ProjectSwitcher() {
  const { data } = useQuery({ queryKey: sessionKey, queryFn: () => api<SessionInfo>('/session'), staleTime: 60_000 })
  const projects = data?.projects ?? []
  const canCreate = data?.can_create_projects === true
  const requests = data?.pending_count ?? 0
  if (projects.length < 2 && !canCreate && requests === 0) return null
  return (
    <>
      {projects.length >= 2 && (
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
                {p.pending ? ` (${ru.approval.badge})` : ''}
              </option>
            ))}
          </select>
        </label>
      )}
      {requests > 0 && (
        <a
          href="/requests"
          className="mx-3 mt-3 flex min-h-touch items-center justify-between gap-2 rounded-lg border border-brass/50 px-3 text-sm text-paper transition-colors duration-fast hover:border-brass"
        >
          {ru.approval.linkLabel}
          <span className="mono rounded-full bg-brass px-2 py-0.5 text-xs font-semibold text-on-brass">{requests}</span>
        </a>
      )}
      {canCreate && (
        <a
          href="/new-project"
          className="mx-3 mt-3 flex min-h-touch items-center gap-2 rounded-lg border border-dashed border-line px-3 text-sm text-fog transition-colors duration-fast hover:border-brass/60 hover:text-paper"
        >
          <Plus size={16} aria-hidden />
          {ru.projects.newLink}
        </a>
      )}
    </>
  )
}
