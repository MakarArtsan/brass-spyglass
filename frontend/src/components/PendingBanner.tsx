import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Hourglass } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { meKey, sessionKey } from '@/hooks/useAuth'
import { api, ApiError, type Project, type SessionInfo } from '@/lib/api'
import { toast } from '@/lib/toast'
import { ru } from '@/ru'

/** Плашка над содержимым, пока проект не подтверждён. Владельцу сайта — с кнопками решения. */
export function PendingBanner({ project }: { project: Project }) {
  const qc = useQueryClient()
  const session = useQuery({ queryKey: sessionKey, queryFn: () => api<SessionInfo>('/session'), staleTime: 60_000 })
  const admin = session.data?.is_superadmin === true

  const decide = useMutation({
    mutationFn: (action: 'approve' | 'reject') => api<{ status: string }>(`/projects/${encodeURIComponent(project.slug)}/${action}`, { method: 'POST' }),
    onSuccess: async (result) => {
      if (result.status === 'reject') {
        toast(ru.approval.rejected)
        window.location.assign('/') // проект ушёл в архив: показываем остальные
        return
      }
      toast(ru.approval.approved)
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['project'] }),
        qc.invalidateQueries({ queryKey: meKey }),
        qc.invalidateQueries({ queryKey: sessionKey }),
      ])
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : ru.common.saveFailed),
  })

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-brass/40 bg-chart px-4 py-3 text-sm lg:px-8"
    >
      <Hourglass size={18} aria-hidden className="shrink-0 text-brass" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{ru.approval.bannerTitle}</p>
        <p className="text-fog">{admin ? ru.approval.bannerAdmin : ru.approval.bannerLead}</p>
      </div>
      {admin && (
        <div className="flex gap-2">
          <Button onClick={() => decide.mutate('approve')} disabled={decide.isPending}>
            {decide.isPending ? ru.approval.deciding : ru.approval.approve}
          </Button>
          <Button variant="outline" onClick={() => decide.mutate('reject')} disabled={decide.isPending}>
            {ru.approval.reject}
          </Button>
        </div>
      )}
    </div>
  )
}
