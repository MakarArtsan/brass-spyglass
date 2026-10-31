import { AudioLines, Check, FileText, Film, Image as ImageIcon, Link2, LayoutGrid, List, Loader2, Search, Send } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Avatar } from '@/components/Avatar'
import { Lens } from '@/components/Lens'
import { useUsers } from '@/hooks/useAuth'
import { displayName } from '@/lib/files'
import { formatDate } from '@/lib/format'
import { useLibrary, type LibraryFilter } from '@/lib/queries'
import type { LibraryItem } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const ICONS = { video: Film, image: ImageIcon, audio: AudioLines, document: FileText, link: Link2 } as const
const KINDS = ['', 'video', 'image', 'audio', 'document', 'link']
const SOURCES = ['', 'upload', 'telegram', 'link']
const VIEW_KEY = 'library-view'

function fromParams(params: URLSearchParams): LibraryFilter {
  const author = Number(params.get('author'))
  return {
    kind: params.get('kind') ?? undefined,
    source: params.get('source') ?? undefined,
    author: Number.isInteger(author) && author > 0 ? author : undefined,
    since: params.get('since') ?? undefined,
    until: params.get('until') ?? undefined,
    unattached: params.has('unattached') || undefined,
    q: params.get('q') ?? undefined,
  }
}

/** Страница хранит фильтры в адресе (ссылкой можно поделиться), окно выбора — в памяти. */
function useFilter(mode: 'page' | 'picker'): [LibraryFilter, (patch: Partial<LibraryFilter>) => void, () => void] {
  const [params, setParams] = useSearchParams()
  const [local, setLocal] = useState<LibraryFilter>({})
  const filter = mode === 'page' ? fromParams(params) : local
  const set = (patch: Partial<LibraryFilter>) => {
    if (mode === 'picker') return setLocal((cur) => ({ ...cur, ...patch }))
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(patch)) {
          if (value === undefined || value === '' || value === false) next.delete(key)
          else next.set(key, value === true ? '1' : String(value))
        }
        return next
      },
      { replace: true },
    )
  }
  const reset = () => (mode === 'picker' ? setLocal({}) : setParams(new URLSearchParams(), { replace: true }))
  return [filter, set, reset]
}

const chip = (active: boolean) =>
  cn(
    'min-h-[44px] rounded-full border px-3.5 text-sm transition-colors duration-fast focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass',
    active ? 'border-brass bg-brass/15 text-paper' : 'border-line text-fog hover:border-brass/50 hover:text-paper',
  )

interface Props {
  mode: 'page' | 'picker'
  selected?: ReadonlySet<number>
  /** Окно выбора: отметить/снять файл. */
  onPick?: (item: LibraryItem) => void
  /** Страница: открыть файл (получает все загруженные, чтобы листать). */
  onOpen?: (item: LibraryItem, all: LibraryItem[]) => void
}

function Thumb({ item, size }: { item: LibraryItem; size: number }) {
  const Icon = ICONS[item.kind]
  return (
    <Lens decorative size={size} src={item.urls.thumb} alt={displayName(item)}>
      <span className="flex h-full w-full items-center justify-center bg-ink text-brass">
        {item.processing ? <Loader2 size={size / 3} className="animate-spin" aria-label={ru.library.processing} /> : <Icon size={size / 3} />}
      </span>
    </Lens>
  )
}

function Badges({ item }: { item: LibraryItem }) {
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-fog">
      {item.source === 'telegram' && <Send size={12} aria-label={ru.files.fromTelegram} />}
      {item.attachments_count > 0 ? (
        <span title={item.attachments.map((a) => a.label).filter(Boolean).join(', ')}>{ru.library.usedIn}: {item.attachments_count}</span>
      ) : (
        <span>{ru.library.notUsed}</span>
      )}
    </span>
  )
}

/** Медиатека: все файлы проекта сеткой и списком с фильтрами; та же сетка выбирает файлы для карточки. */
export function LibraryView({ mode, selected, onPick, onOpen }: Props) {
  const [filter, setFilter, reset] = useFilter(mode)
  const { data: users } = useUsers()
  const query = useLibrary(filter)
  const items = query.data?.pages.flatMap((p) => p.items) ?? []
  const total = query.data?.pages[0]?.total ?? 0
  const [view, setView] = useState<'grid' | 'list'>(() => {
    try {
      return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'grid'
    } catch {
      return 'grid'
    }
  })
  const [text, setText] = useState(filter.q ?? '')
  const timer = useRef<number>()
  const sentinel = useRef<HTMLDivElement>(null)
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query

  const changeView = (next: 'grid' | 'list') => {
    setView(next)
    try {
      localStorage.setItem(VIEW_KEY, next)
    } catch {
      /* хранилище недоступно — вид просто не запомнится */
    }
  }
  const onSearch = (value: string) => {
    setText(value)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setFilter({ q: value.trim() }), 300)
  }

  useEffect(() => {
    const el = sentinel.current
    if (!el || !hasNextPage) return undefined
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage()
      },
      { rootMargin: '600px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  const filtered = Object.values(filter).some((v) => v !== undefined && v !== '' && v !== false)
  const press = (item: LibraryItem) => (mode === 'picker' ? onPick?.(item) : onOpen?.(item, items))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[200px] flex-1">
          <span className="sr-only">{ru.library.searchLabel}</span>
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fog" aria-hidden />
          <input
            type="search"
            value={text}
            onChange={(e) => onSearch(e.target.value)}
            placeholder={ru.library.search}
            className="min-h-touch w-full rounded-lg border border-line bg-ink pl-9 pr-3 text-base text-paper outline-none focus:border-brass"
          />
        </label>
        <div role="group" aria-label={ru.library.view} className="flex rounded-lg border border-line">
          {(['grid', 'list'] as const).map((v) => {
            const Icon = v === 'grid' ? LayoutGrid : List
            return (
              <button key={v} type="button" onClick={() => changeView(v)} aria-pressed={view === v} aria-label={ru.library[v]} className={cn('flex min-h-touch min-w-touch items-center justify-center rounded-lg', view === v ? 'bg-brass/15 text-brass' : 'text-fog hover:text-paper')}>
                <Icon size={18} />
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={ru.library.kinds['']}>
        {KINDS.map((kind) => (
          <button key={kind || 'all'} type="button" aria-pressed={(filter.kind ?? '') === kind} onClick={() => setFilter({ kind: kind || undefined })} className={chip((filter.kind ?? '') === kind)}>
            {ru.library.kinds[kind]}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={ru.library.sources['']}>
        {SOURCES.map((source) => (
          <button key={source || 'any'} type="button" aria-pressed={(filter.source ?? '') === source} onClick={() => setFilter({ source: source || undefined })} className={chip((filter.source ?? '') === source)}>
            {ru.library.sources[source]}
          </button>
        ))}
        <button type="button" aria-pressed={Boolean(filter.unattached)} onClick={() => setFilter({ unattached: !filter.unattached })} className={chip(Boolean(filter.unattached))}>
          {ru.library.unattached}
        </button>
      </div>
      <div className="flex flex-wrap items-end gap-3 text-xs text-fog">
        <label className="flex flex-col gap-1">
          {ru.library.author}
          <select value={filter.author ?? ''} onChange={(e) => setFilter({ author: e.target.value ? Number(e.target.value) : undefined })} className="min-h-touch rounded-lg border border-line bg-ink px-2 text-sm text-paper">
            <option value="">{ru.library.anyAuthor}</option>
            {(users ?? []).map((u) => (
              <option key={u.id} value={u.id}>{u.name}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          {ru.library.since}
          <input type="date" value={filter.since ?? ''} max={filter.until} onChange={(e) => setFilter({ since: e.target.value || undefined })} className="min-h-touch rounded-lg border border-line bg-ink px-2 text-sm text-paper" />
        </label>
        <label className="flex flex-col gap-1">
          {ru.library.until}
          <input type="date" value={filter.until ?? ''} min={filter.since} onChange={(e) => setFilter({ until: e.target.value || undefined })} className="min-h-touch rounded-lg border border-line bg-ink px-2 text-sm text-paper" />
        </label>
        {filtered && (
          <button type="button" onClick={() => { reset(); setText('') }} className="min-h-touch px-2 text-sm text-brass hover:text-brass-light">
            {ru.library.reset}
          </button>
        )}
        <span className="mono ml-auto pb-3 text-fog" role="status">{query.isSuccess ? ru.library.total(total) : ''}</span>
      </div>

      {query.isPending && <p className="py-8 text-center text-fog" role="status">{ru.library.loading}</p>}
      {query.isSuccess && items.length === 0 && <p className="py-10 text-center text-fog">{filtered ? ru.library.empty : ru.library.emptyAll}</p>}

      {view === 'grid' ? (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-x-3 gap-y-5">
          {items.map((item) => {
            const picked = selected?.has(item.id) ?? false
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => press(item)}
                  aria-pressed={mode === 'picker' ? picked : undefined}
                  aria-label={`${mode === 'picker' ? ru.library.select : ru.files.open}: ${displayName(item)}`}
                  className="group flex w-full flex-col items-center gap-1.5 rounded-xl p-1.5 text-center focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass"
                >
                  <span className="relative">
                    <Thumb item={item} size={96} />
                    {picked && (
                      <span className="absolute -right-1 -top-1 flex h-7 w-7 items-center justify-center rounded-full bg-brass text-on-brass ring-2 ring-ink">
                        <Check size={16} aria-label={ru.library.selected} />
                      </span>
                    )}
                  </span>
                  <span className="w-full truncate text-xs" title={displayName(item)}>{displayName(item)}</span>
                  <span className="w-full truncate text-[11px] text-fog">
                    {item.uploaded_by?.name ?? ru.journal.system} · {formatDate(item.uploaded_at)}
                  </span>
                  <Badges item={item} />
                </button>
              </li>
            )
          })}
        </ul>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {items.map((item) => {
            const picked = selected?.has(item.id) ?? false
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => press(item)}
                  aria-pressed={mode === 'picker' ? picked : undefined}
                  className={cn('flex min-h-[56px] w-full items-center gap-3 px-3 py-2 text-left hover:bg-ink/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass', picked && 'bg-brass/10')}
                >
                  <Thumb item={item} size={44} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{displayName(item)}</span>
                    <span className="block truncate text-xs text-fog">
                      {ru.library.kinds[item.kind]} · {ru.library.sources[item.source]}
                    </span>
                  </span>
                  <span className="hidden items-center gap-2 text-xs text-fog sm:flex">
                    {item.uploaded_by && <Avatar user={item.uploaded_by} className="h-6 w-6 text-[10px]" />}
                    <span>{item.uploaded_by?.name}</span>
                    <span className="mono">{formatDate(item.uploaded_at)}</span>
                  </span>
                  <Badges item={item} />
                  {picked && <Check size={18} className="text-brass" aria-label={ru.library.selected} />}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <div ref={sentinel} aria-hidden className="h-px" />
      {hasNextPage && (
        <div className="flex justify-center">
          <button type="button" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage} className="min-h-touch rounded-lg border border-line px-5 text-sm hover:border-brass/60">
            {isFetchingNextPage ? ru.library.loading : ru.library.more}
          </button>
        </div>
      )}
    </div>
  )
}
