import * as Dialog from '@radix-ui/react-dialog'
import { ArrowLeft, AudioLines, Check, Eye, FileText, Film, Image as ImageIcon, Link2, Loader2, Search, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { hostOf } from '@/lib/files'
import { clock, formatDateTime } from '@/lib/format'
import { toast } from '@/lib/toast'
import { useTgImport, useTgMedia, useTgTopics, useTgView, type TgFilter, type TgMediaItem } from '@/lib/telegram'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const KINDS = ['image', 'video', 'audio', 'document', 'link'] as const
const ICONS = { image: ImageIcon, video: Film, audio: AudioLines, document: FileText, link: Link2 } as const

interface Props {
  entityType: string
  entityId: number
  /** Назначение по умолчанию (референс, дубль, звук…). */
  purpose: string
  onClose: () => void
}

/** Альбом — это подряд идущие сообщения с одним `grouped_id`. */
function groupAlbums(items: TgMediaItem[]): { key: string; items: TgMediaItem[] }[] {
  const groups: { key: string; items: TgMediaItem[] }[] = []
  for (const item of items) {
    const last = groups[groups.length - 1]
    if (item.grouped_id !== null && last && last.items[0].grouped_id === item.grouped_id) last.items.push(item)
    else groups.push({ key: `${item.grouped_id ?? 'm'}-${item.id}`, items: [item] })
  }
  return groups
}

const title = (item: TgMediaItem): string =>
  item.kind === 'link' ? hostOf(item.url) : (item.file_name ?? item.caption ?? ru.tg.kinds[item.kind])

function Viewer({ item, onClose }: { item: TgMediaItem; onClose: () => void }) {
  const { data, isError } = useTgView(item.id)
  const url = data?.ready ? data.url : null
  const isPdf = item.mime === 'application/pdf'
  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-ink/95" role="region" aria-label={ru.tg.view}>
      <div className="flex items-center justify-between gap-3 border-b border-line p-3">
        <div className="min-w-0 text-sm">
          <div className="truncate font-medium">{title(item)}</div>
          <div className="truncate text-xs text-fog">
            {item.author_name ?? ru.common.dash} · {formatDateTime(item.posted_at)}
          </div>
        </div>
        <button type="button" onClick={onClose} className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.tg.close}>
          <X size={20} />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center p-3">
        {!url && !isError && (
          <div className="flex flex-col items-center gap-3 text-fog" role="status">
            {item.thumb_url && <img src={item.thumb_url} alt="" className="max-h-48 rounded-lg opacity-60" />}
            <Loader2 className="animate-spin" aria-hidden />
            {ru.tg.fetching}
          </div>
        )}
        {isError && <p role="alert" className="text-alert">{ru.common.saveFailed}</p>}
        {url && item.kind === 'image' && <img src={url} alt={title(item)} className="max-h-full max-w-full object-contain" />}
        {url && item.kind === 'video' && <video src={url} controls autoPlay playsInline className="max-h-full max-w-full" />}
        {url && item.kind === 'audio' && <audio src={url} controls autoPlay className="w-full max-w-md" />}
        {url && item.kind === 'document' && (isPdf ? <iframe src={url} title={title(item)} className="h-full w-full rounded-lg bg-white" /> : <p className="text-sm text-fog">{ru.tg.noPreview}</p>)}
      </div>
    </div>
  )
}

function Tile({
  item,
  picked,
  onToggle,
  onView,
}: {
  item: TgMediaItem
  picked: boolean
  onToggle: () => void
  onView: () => void
}) {
  const Icon = ICONS[item.kind]
  const label = item.caption ?? title(item) // то же, что видно под плиткой
  return (
    <div className={cn('relative flex w-[112px] flex-col gap-1 self-start', picked && 'rounded-xl bg-brass/10')}>
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={picked}
        aria-label={`${picked ? ru.tg.selected : ru.tg.select}: ${label}`}
        className={cn(
          'relative flex aspect-square w-full items-center justify-center overflow-hidden rounded-xl border bg-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass',
          picked ? 'border-brass' : 'border-line hover:border-brass/50',
        )}
      >
        {item.thumb_url ? <img src={item.thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" /> : <Icon size={32} className="text-brass" aria-hidden />}
        {item.kind === 'video' && item.duration_sec != null && <span className="mono absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[10px]">{clock(item.duration_sec)}</span>}
        {item.imported_file_id !== null && <span className="absolute bottom-1 left-1 rounded bg-status-done/80 px-1 text-[10px] text-ink">{ru.tg.imported}</span>}
        {picked && (
          <span className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-brass text-on-brass">
            <Check size={14} aria-hidden />
          </span>
        )}
      </button>
      {item.kind !== 'link' && (
        <button type="button" onClick={onView} aria-label={`${ru.tg.view}: ${label}`} className="absolute left-1 top-1 flex h-9 w-9 items-center justify-center rounded-full bg-black/60 text-paper hover:bg-black/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass">
          <Eye size={16} aria-hidden />
        </button>
      )}
      <span className="truncate px-1 text-[11px] text-fog" title={label}>
        {label}
      </span>
    </div>
  )
}

/**
 * «Открыл карточку → значок Telegram → выбрал тему → увидел все медиа темы → отметил нужные → они загрузились
 * в карточку» (ТЗ). Слева темы чата, справа сетка медиа; на телефоне сначала темы, потом медиа.
 */
export default function TelegramWindow({ entityType, entityId, purpose, onClose }: Props) {
  const { data: topics } = useTgTopics()
  const [topicId, setTopicId] = useState<number | null>(null)
  const [step, setStep] = useState<'topics' | 'media'>('topics')
  const [kinds, setKinds] = useState<string[]>([])
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [hideImported, setHideImported] = useState(false)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [chosenPurpose, setChosenPurpose] = useState(purpose)
  const [viewing, setViewing] = useState<TgMediaItem | null>(null)
  const timer = useRef<number>()
  const sentinel = useRef<HTMLDivElement>(null)
  const importer = useTgImport(entityType, entityId)

  // На ПК сразу открыта самая наполненная тема; на телефоне сначала список тем.
  const desktop = useIsDesktop()
  const activeTopic = topicId ?? (desktop ? (topics?.[0]?.topic_id ?? null) : null)
  const filter: TgFilter = { topicId: activeTopic, kinds, q, hideImported }
  const media = useTgMedia(filter)
  const items = useMemo(() => media.data?.pages.flatMap((p) => p.items) ?? [], [media.data])
  const groups = useMemo(() => groupAlbums(items), [items])
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = media

  useEffect(() => {
    const el = sentinel.current
    if (!el || !hasNextPage) return undefined
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage()
      },
      { rootMargin: '500px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  const toggle = (id: number) =>
    setPicked((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const toggleAlbum = (album: TgMediaItem[]) =>
    setPicked((cur) => {
      const next = new Set(cur)
      const all = album.every((i) => next.has(i.id))
      for (const i of album) {
        if (all) next.delete(i.id)
        else next.add(i.id)
      }
      return next
    })
  const toggleKind = (kind: string) => setKinds((cur) => (cur.includes(kind) ? cur.filter((k) => k !== kind) : [...cur, kind]))
  const onSearch = (value: string) => {
    setText(value)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setQ(value), 300)
  }
  const openTopic = (id: number) => {
    setTopicId(id)
    setStep('media')
    setPicked(new Set())
  }

  const submit = () =>
    importer.mutate(
      { mediaIds: [...picked], purpose: chosenPurpose },
      {
        onSuccess: (result) => {
          toast(ru.tg.started(result.count))
          onClose()
        },
      },
    )

  const topicList = (
    <nav aria-label={ru.tg.topics} className={cn('min-h-0 overflow-y-auto border-line p-2 lg:block lg:w-[260px] lg:shrink-0 lg:border-r', step === 'media' ? 'hidden' : 'block flex-1')}>
      <h3 className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-fog">{ru.tg.topics}</h3>
      {topics && topics.length === 0 && <p className="p-3 text-sm text-fog">{ru.tg.noTopics}</p>}
      <ul>
        {topics?.map((t) => (
          <li key={t.topic_id}>
            <button
              type="button"
              onClick={() => openTopic(t.topic_id)}
              aria-current={activeTopic === t.topic_id ? 'true' : undefined}
              className={cn('flex min-h-[56px] w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-ink/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass', activeTopic === t.topic_id && 'bg-brass/10')}
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-brass/50 bg-ink text-sm font-semibold text-brass">
                {t.latest_thumb_url ? <img src={t.latest_thumb_url} alt="" className="h-full w-full object-cover" /> : (t.icon_emoji ?? t.title.slice(0, 1).toUpperCase())}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">{t.title}</span>
                <span className="mono block text-xs text-fog">{ru.tg.mediaCount(t.media_count)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/60" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[91] flex h-[min(94dvh,800px)] w-[min(98vw,1120px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-line bg-chart shadow-2xl outline-none">
          <div className="flex items-start justify-between gap-3 border-b border-line p-4">
            <div className="min-w-0">
              <Dialog.Title className="font-display text-2xl">{ru.tg.title}</Dialog.Title>
              <Dialog.Description className="text-sm text-fog">{ru.tg.lead}</Dialog.Description>
            </div>
            <Dialog.Close className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.tg.close}>
              <X size={18} />
            </Dialog.Close>
          </div>

          <div className="relative flex min-h-0 flex-1 flex-col lg:flex-row">
            {topicList}
            <section className={cn('min-h-0 flex-1 flex-col lg:flex', step === 'media' ? 'flex' : 'hidden')} aria-label={ru.tg.mediaCount(items.length)}>
              <div className="space-y-3 border-b border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" onClick={() => setStep('topics')} className="inline-flex min-h-touch items-center gap-1.5 rounded-lg px-2 text-sm text-brass lg:hidden">
                    <ArrowLeft size={16} aria-hidden />
                    {ru.tg.backToTopics}
                  </button>
                  <label className="relative min-w-[160px] flex-1">
                    <span className="sr-only">{ru.tg.searchLabel}</span>
                    <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fog" aria-hidden />
                    <input type="search" value={text} onChange={(e) => onSearch(e.target.value)} placeholder={ru.tg.search} className="min-h-touch w-full rounded-lg border border-line bg-ink pl-9 pr-3 text-base outline-none focus:border-brass" />
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-2" role="group" aria-label={ru.tg.filters}>
                  {KINDS.map((kind) => (
                    <button key={kind} type="button" aria-pressed={kinds.includes(kind)} onClick={() => toggleKind(kind)} className={cn('min-h-[44px] rounded-full border px-3.5 text-sm', kinds.includes(kind) ? 'border-brass bg-brass/15' : 'border-line text-fog hover:border-brass/50')}>
                      {ru.tg.kinds[kind]}
                    </button>
                  ))}
                  <label className="ml-auto flex min-h-[44px] cursor-pointer items-center gap-2 text-sm text-fog">
                    <input type="checkbox" checked={hideImported} onChange={(e) => setHideImported(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--brass))]" />
                    {ru.tg.hideImported}
                  </label>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {activeTopic === null && <p className="py-10 text-center text-fog">{ru.tg.chooseTopic}</p>}
                {activeTopic !== null && media.isPending && <p className="py-10 text-center text-fog" role="status">{ru.tg.loading}</p>}
                {activeTopic !== null && media.isSuccess && items.length === 0 && <p className="py-10 text-center text-fog">{ru.tg.empty}</p>}
                <div className="flex flex-wrap gap-x-3 gap-y-4">
                  {groups.map((group) =>
                    group.items.length === 1 ? (
                      <Tile key={group.key} item={group.items[0]} picked={picked.has(group.items[0].id)} onToggle={() => toggle(group.items[0].id)} onView={() => setViewing(group.items[0])} />
                    ) : (
                      <div key={group.key} className="rounded-2xl border border-dashed border-brass/40 p-2" role="group" aria-label={ru.tg.album(group.items.length)}>
                        <label className="mb-2 flex min-h-[44px] cursor-pointer items-center gap-2 text-xs text-fog">
                          <input type="checkbox" checked={group.items.every((i) => picked.has(i.id))} onChange={() => toggleAlbum(group.items)} className="h-4 w-4 accent-[rgb(var(--brass))]" />
                          {ru.tg.album(group.items.length)} · {ru.tg.selectAlbum}
                        </label>
                        <div className="flex flex-wrap gap-3">
                          {group.items.map((item) => (
                            <Tile key={item.id} item={item} picked={picked.has(item.id)} onToggle={() => toggle(item.id)} onView={() => setViewing(item)} />
                          ))}
                        </div>
                      </div>
                    ),
                  )}
                </div>
                <div ref={sentinel} aria-hidden className="h-px" />
                {hasNextPage && (
                  <div className="flex justify-center pt-4">
                    <button type="button" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage} className="min-h-touch rounded-lg border border-line px-5 text-sm hover:border-brass/60">
                      {isFetchingNextPage ? ru.tg.loading : ru.tg.more}
                    </button>
                  </div>
                )}
              </div>
            </section>
            {viewing && <Viewer item={viewing} onClose={() => setViewing(null)} />}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line p-3">
            <label className="flex items-center gap-2 text-sm text-fog">
              {ru.tg.purpose}
              <select value={chosenPurpose} onChange={(e) => setChosenPurpose(e.target.value)} className="min-h-touch rounded-lg border border-line bg-ink px-2 text-paper">
                {Object.entries(ru.purpose).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <Button type="button" onClick={submit} disabled={picked.size === 0 || importer.isPending}>
              {ru.tg.add(picked.size)}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
