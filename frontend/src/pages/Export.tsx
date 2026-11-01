import { Download, Loader2, Package, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Avatar } from '@/components/Avatar'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { useMe } from '@/hooks/useAuth'
import { ApiError } from '@/lib/api'
import {
  useCreateExport,
  useExportPreview,
  useExports,
  type ExportItem,
  type ExportLevel,
  type ExportParams,
  type ExportTarget,
} from '@/lib/exports'
import { clock, formatDate, formatDateTime, formatSize } from '@/lib/format'
import { toast } from '@/lib/toast'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const STORE_KEY = 'bs.export.params'

function loadParams(): ExportParams {
  const fallback: ExportParams = { target: 'resolve', level: 'scenes', placeholders: false, references: false, media_root: '' }
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? '{}') as Partial<ExportParams>
    return { ...fallback, ...saved }
  } catch {
    return fallback
  }
}

function Segment<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'min-h-touch rounded-full border px-4 text-sm font-semibold transition-colors duration-fast',
            value === o.value ? 'border-brass bg-brass/15 text-brass-light' : 'border-line text-fog hover:border-fog hover:text-paper',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Check({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string }) {
  return (
    <label className="flex min-h-touch cursor-pointer items-start gap-3 py-1.5">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-5 w-5 accent-brass" />
      <span>
        <span className="block text-sm font-semibold">{label}</span>
        <span className="block text-xs text-fog">{hint}</span>
      </span>
    </label>
  )
}

function HistoryRow({ item }: { item: ExportItem }) {
  const running = item.status === 'queued' || item.status === 'running'
  return (
    <li className="rounded-xl border border-line bg-chart p-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {item.created_by && <Avatar user={item.created_by} className="h-8 w-8" />}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">
            {ru.exportPage[item.target]} · {item.level === 'scenes' ? ru.exportPage.levelScenes : ru.exportPage.levelShots}
            {item.placeholders && <span className="ml-2 text-xs font-normal text-fog">+ {ru.exportPage.options.placeholders}</span>}
            {item.references && <span className="ml-2 text-xs font-normal text-fog">+ {ru.exportPage.options.references}</span>}
          </div>
          <div className="text-xs text-fog">
            {formatDateTime(item.created_at)} · {ru.exportPage.by(item.created_by?.name ?? ru.journal.system)}
          </div>
        </div>
        <span
          className={cn(
            'rounded-full border px-3 py-0.5 text-xs font-semibold',
            item.status === 'done' && 'border-status-done/50 text-status-done',
            item.status === 'failed' && 'border-alert/50 text-alert',
            running && 'border-brass/50 text-brass',
          )}
        >
          {running && <Loader2 size={12} className="mr-1 inline animate-spin" aria-hidden />}
          {ru.exportPage.status[item.status]}
          {running && item.progress > 0 ? ` ${Math.round(item.progress * 100)}%` : ''}
        </span>
        {item.available && item.download_url && (
          <a
            href={item.download_url}
            className="inline-flex min-h-touch items-center gap-2 rounded-lg bg-brass px-4 text-sm font-semibold text-on-brass hover:bg-brass-light"
          >
            <Download size={16} aria-hidden />
            {ru.exportPage.download}
          </a>
        )}
      </div>
      {running && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(item.progress * 100)}>
          <div className="h-full bg-brass transition-[width] duration-base" style={{ width: `${Math.max(4, item.progress * 100)}%` }} />
        </div>
      )}
      {item.status === 'done' && item.result && (
        <p className="mt-2 text-xs text-fog">
          {ru.exportPage.result(item.result.clips, item.result.placeholders, formatSize(item.result.size_bytes))}
          {item.available && ` · ${ru.exportPage.keptUntil(formatDate(item.expires_at))}`}
        </p>
      )}
      {item.status === 'done' && item.expired && <p className="mt-2 text-xs text-fog">{ru.exportPage.expired}</p>}
      {item.status === 'failed' && item.error && (
        <p className="mt-2 flex items-start gap-2 text-xs text-alert" role="alert">
          <TriangleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />
          {item.error}
        </p>
      )}
    </li>
  )
}

/** Экспорт в DaVinci Resolve и Premiere Pro: параметры, что попадёт на таймлайн, история выгрузок. */
export default function Export() {
  const { data: me } = useMe()
  const [params, setParams] = useState<ExportParams>(loadParams)
  const preview = useExportPreview(params.level, params.placeholders, params.references)
  const history = useExports()
  const create = useCreateExport()

  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(params))
    } catch {
      /* хранилище недоступно — просто не запоминаем */
    }
  }, [params])

  if (me && !me.abilities.export) return <Navigate to="/" replace />
  const set = <K extends keyof ExportParams>(key: K, value: ExportParams[K]) => setParams((p) => ({ ...p, [key]: value }))
  const data = preview.data

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(params, {
      onSuccess: () => toast(ru.exportPage.started),
      onError: (e) => toast(e instanceof ApiError ? e.message : ru.common.saveFailed),
    })
  }

  return (
    <section>
      <PageHeader title={ru.exportPage.title} lead={ru.exportPage.lead} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-line bg-chart/60 p-5" aria-label={ru.exportPage.params}>
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.exportPage.program}</div>
            <Segment<ExportTarget>
              label={ru.exportPage.program}
              value={params.target}
              onChange={(v) => set('target', v)}
              options={[
                { value: 'resolve', label: ru.exportPage.resolve },
                { value: 'premiere', label: ru.exportPage.premiere },
              ]}
            />
          </div>
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.exportPage.level}</div>
            <Segment<ExportLevel>
              label={ru.exportPage.level}
              value={params.level}
              onChange={(v) => set('level', v)}
              options={[
                { value: 'scenes', label: ru.exportPage.levelScenes },
                { value: 'shots', label: ru.exportPage.levelShots },
              ]}
            />
            <p className="mt-1.5 text-xs text-fog">{ru.exportPage.levelHint[params.level]}</p>
          </div>
          <Check checked={params.placeholders} onChange={(v) => set('placeholders', v)} label={ru.exportPage.placeholders} hint={ru.exportPage.placeholdersHint} />
          <Check checked={params.references} onChange={(v) => set('references', v)} label={ru.exportPage.references} hint={ru.exportPage.referencesHint} />
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.exportPage.folder}</span>
            <input
              value={params.media_root}
              onChange={(e) => set('media_root', e.target.value)}
              placeholder={ru.exportPage.folderPlaceholder}
              maxLength={260}
              className="mono min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass"
            />
            <span className="mt-1 block text-xs text-fog">{ru.exportPage.folderHint}</span>
          </label>
          <Button type="submit" size="lg" disabled={create.isPending} className="w-full">
            {create.isPending ? <Loader2 size={18} className="animate-spin" aria-hidden /> : <Package size={18} aria-hidden />}
            {create.isPending ? ru.exportPage.building : ru.exportPage.build}
          </Button>
        </form>

        <div className="min-w-0 space-y-3">
          <h2 className="text-2xl">{ru.exportPage.preview}</h2>
          {!data ? (
            <p className="text-sm text-fog">{ru.common.loading}</p>
          ) : data.clips.length === 0 ? (
            <p className="rounded-xl border border-dashed border-line p-4 text-sm text-fog">{ru.exportPage.previewEmpty}</p>
          ) : (
            <>
              <p className="text-sm">{ru.exportPage.previewSummary(data.ready, data.placeholders, clock(data.total_sec))}</p>
              <p className="text-xs text-fog">{ru.exportPage.previewMore(data.audio, data.subtitles, data.references)}</p>
              <ol className="max-h-[360px] space-y-1 overflow-y-auto rounded-xl border border-line p-2" aria-label={ru.exportPage.preview}>
                {data.clips.map((c, i) => (
                  <li key={`${c.name}-${i}`} className={cn('flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm', c.kind === 'placeholder' && 'text-fog')}>
                    <span className="mono w-24 shrink-0 text-xs text-brass">{c.timecode}</span>
                    <span className="min-w-0 flex-1 truncate">{c.label}</span>
                    {c.kind === 'placeholder' && <span className="rounded-full border border-line px-2 text-[10px] uppercase">{ru.exportPage.placeholderTag}</span>}
                    <span className="mono w-12 shrink-0 text-right text-xs">{clock(c.seconds)}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
          {data && data.skipped.length > 0 && (
            <details className="rounded-xl border border-line p-3 text-sm">
              <summary className="min-h-touch cursor-pointer leading-[44px] text-fog">{ru.exportPage.skipped(data.skipped.length)}</summary>
              <ul className="mt-1 space-y-1 text-xs text-fog">
                {data.skipped.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>

      <h2 className="mb-3 mt-10 text-2xl">{ru.exportPage.history}</h2>
      {history.data?.length === 0 && <p className="text-sm text-fog">{ru.exportPage.historyEmpty}</p>}
      <ul className="space-y-3">{history.data?.map((item) => <HistoryRow key={item.id} item={item} />)}</ul>
    </section>
  )
}
