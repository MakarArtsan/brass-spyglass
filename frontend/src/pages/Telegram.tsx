import { RefreshCw } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { usePerms } from '@/hooks/usePerms'
import { formatDateTime } from '@/lib/format'
import { toast } from '@/lib/toast'
import { useTgStatus, useTgSync, useTgTopics } from '@/lib/telegram'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

/** Служебный экран: подключение юзербота, темы чата и состояние синхронизации (ТЗ). */
export default function Telegram() {
  const perms = usePerms()
  const { data: status } = useTgStatus()
  const { data: topics } = useTgTopics()
  const sync = useTgSync()
  if (perms.role === 'guest') return <p className="text-fog">{ru.tg.guestNote}</p>

  const phase = status?.phase ? ru.tg.phases[status.phase] : ''
  return (
    <div className="space-y-6">
      <PageHeader
        title={ru.tg.screenTitle}
        lead={ru.tg.screenLead}
        actions={
          perms.role === 'owner' && (
            <Button
              type="button"
              variant="outline"
              disabled={!status?.connected || sync.isPending}
              onClick={() => sync.mutate(undefined, { onSuccess: () => toast(ru.tg.syncAsked) })}
            >
              <RefreshCw size={18} />
              {ru.tg.sync}
            </Button>
          )
        }
      />

      {status && (
        <section className="panel grid gap-4 p-4 sm:grid-cols-2">
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-fog">{ru.tg.connection}</h2>
            <p className={cn('mt-1 text-lg font-semibold', status.connected ? 'text-status-done' : 'text-alert')}>
              {status.connected ? ru.tg.connected : ru.tg.notConnected}
            </p>
            {!status.connected && (
              <p className="mt-1 text-sm text-fog">{status.configured ? (status.userbot_error ? null : ru.tg.notConnectedHint) : ru.tg.notConfigured}</p>
            )}
            {!status.connected && status.userbot_error && (
              <p className="mt-1 text-sm text-alert" role="alert">
                {ru.tg.notConnectedReason}: {status.userbot_error}
              </p>
            )}
          </div>
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-fog">{ru.tg.syncState}</h2>
            <p className="mt-1 text-lg font-semibold">{status.syncing ? ru.tg.syncing : ru.tg.idle}</p>
            {status.syncing && (
              <p className="text-sm text-fog" role="status">
                {[phase, status.topic ? ru.tg.topicLabel(status.topic) : null, status.thumbs_left > 0 ? ru.tg.thumbsLeft(status.thumbs_left) : null].filter(Boolean).join(' · ')}
              </p>
            )}
            <p className="mono mt-1 text-xs text-fog">
              {ru.tg.lastRun}: {status.last_run_at ? formatDateTime(status.last_run_at) : ru.tg.never}
            </p>
            {status.overview && <p className="mono text-xs text-fog">{ru.tg.totals(status.overview.topics, status.overview.media)}</p>}
          </div>
          {status.last_error && (
            <p role="alert" className="text-sm text-alert sm:col-span-2">
              {ru.tg.lastError}: {status.last_error}
            </p>
          )}
        </section>
      )}

      <section aria-label={ru.tg.topicTable}>
        <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-fog">{ru.tg.topicTable}</h2>
        {topics && topics.length === 0 && <p className="text-sm text-fog">{ru.tg.noTopics}</p>}
        <ul className="divide-y divide-line rounded-xl border border-line">
          {topics?.map((t) => (
            <li key={t.topic_id} className="flex min-h-[56px] flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-brass/50 bg-ink text-sm font-semibold text-brass">
                {t.latest_thumb_url ? <img src={t.latest_thumb_url} alt="" className="h-full w-full object-cover" /> : t.title.slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1 truncate">{t.title}</span>
              <span className="mono text-sm">{ru.tg.mediaCount(t.media_count)}</span>
              <span className="text-xs text-fog">{t.history_complete ? ru.tg.topicHistory.done : ru.tg.topicHistory.partial}</span>
              <span className="mono text-xs text-fog">{t.last_synced_at ? `${ru.tg.syncedAt}: ${formatDateTime(t.last_synced_at)}` : ''}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
