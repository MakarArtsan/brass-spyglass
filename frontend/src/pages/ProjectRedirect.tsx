import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, ApiError, type SessionInfo } from '@/lib/api'
import { lastProject, rememberProject } from '@/lib/project'
import { sessionKey, useLogout } from '@/hooks/useAuth'
import { ru } from '@/ru'

/** Вне проекта: выбирает проект человека (последний открытый, иначе первый) и переходит в него.
 * Старые ссылки (`/shots?shot=3`) тоже попадают сюда и переносятся в проект целиком. */
export default function ProjectRedirect() {
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: () => api<SessionInfo>('/session'),
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
  })
  const logout = useLogout()
  const projects = session.data?.projects

  useEffect(() => {
    if (session.error instanceof ApiError && session.error.status === 401) {
      window.location.replace('/login')
      return
    }
    if (!projects?.length) return
    const wanted = lastProject()
    const target = projects.find((p) => p.slug === wanted) ?? projects[0]
    rememberProject(target.slug)
    const inner = location.pathname === '/' ? '/' : location.pathname
    window.location.replace(`/p/${encodeURIComponent(target.slug)}${inner}${location.search}${location.hash}`)
  }, [session.error, projects])

  if (projects && projects.length === 0) {
    return (
      <div role="status" className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="font-display text-3xl">{ru.projects.noneTitle}</h1>
        <p className="max-w-md text-fog">{ru.projects.noneLead}</p>
        <button type="button" onClick={() => logout.mutate()} className="min-h-touch rounded-lg border border-line px-4">
          {ru.projects.logout}
        </button>
      </div>
    )
  }
  if (session.isError && !(session.error instanceof ApiError && session.error.status === 401)) {
    return (
      <div role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-3">
        <p>{ru.app.error}</p>
        <button type="button" onClick={() => void session.refetch()} className="min-h-touch rounded-lg border border-line px-4">
          {ru.app.retry}
        </button>
      </div>
    )
  }
  return (
    <div role="status" className="flex min-h-dvh items-center justify-center text-fog">
      {ru.app.loading}
    </div>
  )
}
