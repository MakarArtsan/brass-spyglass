import { AlertTriangle, CheckCircle2, Loader2, X } from 'lucide-react'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { usePerms } from '@/hooks/usePerms'
import { onJobEvent } from '@/lib/live'
import { tgJobsHint, useTgJobs, type TgJob } from '@/lib/telegram'
import { ru } from '@/ru'

const DONE_VISIBLE_MS = 6000

function Row({ job, onDismiss }: { job: TgJob; onDismiss: () => void }) {
  const active = job.status === 'queued' || job.status === 'running'
  const failed = job.status === 'failed'
  const done = Math.round(job.progress * job.total)

  useEffect(() => {
    if (job.status !== 'done') return undefined
    const id = window.setTimeout(onDismiss, DONE_VISIBLE_MS)
    return () => window.clearTimeout(id)
  }, [job.status, onDismiss])

  return (
    <li className="rounded-xl border border-line bg-chart p-3 shadow-xl shadow-black/40" role={failed ? 'alert' : 'status'}>
      <div className="flex items-start gap-2.5">
        {active && <Loader2 size={18} className="mt-0.5 shrink-0 animate-spin text-brass" aria-hidden />}
        {job.status === 'done' && <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-status-done" aria-hidden />}
        {failed && <AlertTriangle size={18} className="mt-0.5 shrink-0 text-alert" aria-hidden />}
        <div className="min-w-0 flex-1 text-sm">
          <div className="font-medium">{failed ? ru.tg.jobFailed : job.status === 'done' ? ru.tg.jobDone : ru.tg.jobsTitle}</div>
          {active && <div className="mono text-xs text-fog">{ru.tg.jobProgress(done, job.total)}</div>}
          {failed && job.error && <div className="text-xs text-fog">{job.error}</div>}
          {active && (
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)} aria-label={ru.tg.jobsTitle}>
              <div className="h-full rounded-full bg-brass transition-[width] duration-200 motion-reduce:transition-none" style={{ width: `${Math.max(4, job.progress * 100)}%` }} />
            </div>
          )}
        </div>
        {!active && (
          <button type="button" onClick={onDismiss} aria-label={ru.tg.dismiss} className="flex min-h-touch min-w-touch items-center justify-center text-fog hover:text-paper">
            <X size={16} />
          </button>
        )}
      </div>
    </li>
  )
}

/** Прогресс импорта из Telegram в углу экрана: окно «Добавить из Telegram» можно закрыть (ТЗ). */
export function TgJobs() {
  const perms = usePerms()
  const mayBeImporting = useSyncExternalStore(tgJobsHint.subscribe, tgJobsHint.get)
  const { data } = useTgJobs(perms.canUpload && mayBeImporting)
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())
  // Импорт мог начаться в другой вкладке или до перезагрузки: прогресс задачи приходит по SSE.
  useEffect(() => onJobEvent((event) => event.job_type === 'tg_import' && tgJobsHint.raise()), [])
  if (!perms.canUpload) return null
  const jobs = (data ?? []).filter((j) => !dismissed.has(j.id))
  if (jobs.length === 0) return null
  return (
    <ul className="pointer-events-none fixed bottom-20 right-3 z-[80] w-[min(92vw,340px)] space-y-2 lg:bottom-4 lg:right-4 [&>li]:pointer-events-auto" aria-label={ru.tg.jobsTitle}>
      {jobs.map((job) => (
        <Row key={job.id} job={job} onDismiss={() => setDismissed((cur) => new Set(cur).add(job.id))} />
      ))}
    </ul>
  )
}
