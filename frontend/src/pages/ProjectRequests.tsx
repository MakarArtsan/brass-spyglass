import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Logo } from '@/components/Logo'
import { StraitMap } from '@/components/StraitMap'
import { Button } from '@/components/ui/button'
import { sessionKey } from '@/hooks/useAuth'
import { api, ApiError, type ProjectRequest } from '@/lib/api'
import { toast } from '@/lib/toast'
import { ru } from '@/ru'

const requestsKey = ['project-requests'] as const

/** Заявки на проекты: только владелец сайта. Решение — подтвердить (команда получает загрузку) или отклонить. */
export default function ProjectRequests() {
  const qc = useQueryClient()
  const list = useQuery({
    queryKey: requestsKey,
    queryFn: () => api<ProjectRequest[]>('/projects/pending'),
    retry: false,
  })

  useEffect(() => {
    if (list.error instanceof ApiError && list.error.status === 401) window.location.replace('/login')
  }, [list.error])

  const decide = useMutation({
    mutationFn: ({ slug, action }: { slug: string; action: 'approve' | 'reject' }) =>
      api<{ status: string }>(`/projects/${encodeURIComponent(slug)}/${action}`, { method: 'POST' }),
    onSuccess: async (result) => {
      toast(result.status === 'reject' ? ru.approval.rejected : ru.approval.approved)
      await Promise.all([qc.invalidateQueries({ queryKey: requestsKey }), qc.invalidateQueries({ queryKey: sessionKey })])
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : ru.common.saveFailed),
  })

  const forbidden = list.error instanceof ApiError && list.error.status === 403

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-4 py-10">
      <StraitMap variant="page" className="absolute inset-0 h-full w-full opacity-90" />
      <div className="absolute inset-0 bg-gradient-to-b from-ink/60 via-ink/30 to-ink" aria-hidden />
      <main className="panel relative w-full max-w-xl p-6 shadow-2xl shadow-black/40 sm:p-8">
        <Logo className="mb-6" withTeam />
        <h1 className="font-display text-4xl leading-none">{ru.approval.title}</h1>
        <p className="mt-3 text-sm text-fog">{ru.approval.lead}</p>

        {list.isPending && (
          <p role="status" className="mt-6 text-fog">
            {ru.newProject.checking}
          </p>
        )}
        {forbidden && (
          <p role="alert" className="mt-6">
            {ru.approval.notAllowed}
          </p>
        )}
        {list.data && list.data.length === 0 && <p className="mt-6 text-fog">{ru.approval.empty}</p>}

        {list.data && list.data.length > 0 && (
          <ul className="mt-6 space-y-3">
            {list.data.map((item) => (
              <li key={item.slug} className="rounded-xl border border-line p-4">
                <p className="font-display text-xl">{item.title}</p>
                <p className="mt-1 text-sm text-fog">
                  {ru.approval.by} {item.owner_name ?? '—'}
                  {item.owner_username ? ` (@${item.owner_username})` : ''}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button onClick={() => decide.mutate({ slug: item.slug, action: 'approve' })} disabled={decide.isPending}>
                    {ru.approval.approve}
                  </Button>
                  <Button variant="outline" onClick={() => decide.mutate({ slug: item.slug, action: 'reject' })} disabled={decide.isPending}>
                    {ru.approval.reject}
                  </Button>
                  <Button asChild variant="ghost">
                    <a href={`/p/${encodeURIComponent(item.slug)}/`}>{ru.approval.open}</a>
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-6">
          <Button asChild variant="ghost">
            <a href="/">{ru.approval.back}</a>
          </Button>
        </div>
      </main>
    </div>
  )
}
