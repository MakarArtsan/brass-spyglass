import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion as fm } from 'framer-motion'
import { Camera, Check, Loader2, Plus, TriangleAlert, X } from 'lucide-react'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  lazy,
  Suspense,
  type ReactNode,
} from 'react'
import { motion } from '@/brand'
import { Button } from '@/components/ui/button'
import { usePerms } from '@/hooks/usePerms'
import { keys } from '@/lib/queries'
import { toast } from '@/lib/toast'
import {
  cancelUpload,
  DuplicateError,
  HttpError,
  uploadFile,
  type UploadTarget,
} from '@/lib/uploader'
import type { DuplicateInfo } from '@/lib/types'
import { formatSize } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

// Диалог тянет Radix Dialog — грузим его, только когда действительно нашёлся дубль.
const DuplicateDialog = lazy(() => import('@/components/DuplicateDialog'))

const MAX_BYTES = 4 * 1024 ** 3
const PARALLEL = 2
const ALLOWED = ['mp4', 'mov', 'webm', 'm4v', 'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif', 'gif', 'wav', 'mp3', 'aiff', 'aif', 'flac', 'm4a', 'ogg', 'oga', 'opus', 'pdf', 'docx', 'txt', 'md', 'xlsx']
// eslint-disable-next-line react-refresh/only-export-components
export const ACCEPT = ALLOWED.map((e) => `.${e}`).join(',')

type State = 'queued' | 'uploading' | 'retrying' | 'done' | 'error' | 'duplicate'

interface Item {
  id: string
  file: File
  target: UploadTarget
  loaded: number
  state: State
  error?: string
  duplicate?: { info: DuplicateInfo; uploadId: string }
}

interface Api {
  items: Item[]
  upload: (files: FileList | File[], target: UploadTarget) => void
}

const Ctx = createContext<Api | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useUploads(): Api {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useUploads вне UploadProvider')
  return ctx
}

const extension = (name: string) => name.split('.').pop()?.toLowerCase() ?? ''

/** Атрибут зоны, на которую можно бросить файл: подсвечивается при перетаскивании. */
// eslint-disable-next-line react-refresh/only-export-components
export const dropZone = (target: UploadTarget) => ({ 'data-drop': JSON.stringify(target) })

function hasFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes('Files')
}

export function UploadProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const perms = usePerms()
  const [items, setItems] = useState<Item[]>([])
  const controllers = useRef(new Map<string, AbortController>())
  const running = useRef(new Set<string>())
  const lastPaint = useRef(0)

  const patch = useCallback((id: string, change: Partial<Item>) => {
    setItems((list) => list.map((i) => (i.id === id ? { ...i, ...change } : i)))
  }, [])

  const refresh = useCallback(
    (target: UploadTarget) => {
      if (target.entityType && target.entityId != null) {
        qc.invalidateQueries({ queryKey: keys.files(target.entityType, target.entityId) })
      }
      for (const k of ['shots', 'assets', 'scenes', 'shot', 'asset', 'activity']) qc.invalidateQueries({ queryKey: [k] })
    },
    [qc],
  )

  const run = useCallback(
    async (item: Item, resume?: { uploadId: string; force: boolean }) => {
      const controller = new AbortController()
      controllers.current.set(item.id, controller)
      running.current.add(item.id)
      patch(item.id, { state: 'uploading', duplicate: undefined })
      try {
        await uploadFile(
          item.file,
          item.target,
          {
            signal: controller.signal,
            onProgress: (loaded) => {
              const now = performance.now()
              if (now - lastPaint.current > 120 || loaded >= item.file.size) {
                lastPaint.current = now
                patch(item.id, { loaded })
              }
            },
            onState: (state) => patch(item.id, { state }),
          },
          resume,
        )
        patch(item.id, { state: 'done', loaded: item.file.size })
        refresh(item.target)
        window.setTimeout(() => setItems((list) => list.filter((i) => i.id !== item.id)), 4000)
      } catch (err) {
        if (err instanceof DOMException) {
          setItems((list) => list.filter((i) => i.id !== item.id))
        } else if (err instanceof DuplicateError) {
          patch(item.id, { state: 'duplicate', duplicate: { info: err.info, uploadId: err.uploadId } })
        } else {
          const message =
            err instanceof HttpError && err.status === 415
              ? ru.files.unsupported
              : err instanceof HttpError && err.status === 413
                ? ru.files.tooBig
                : err instanceof HttpError
                  ? err.message
                  : ru.files.failed
          patch(item.id, { state: 'error', error: message })
        }
      } finally {
        running.current.delete(item.id)
        controllers.current.delete(item.id)
      }
    },
    [patch, refresh],
  )

  // Очередь: не больше PARALLEL файлов одновременно.
  useEffect(() => {
    for (const item of items) {
      if (running.current.size >= PARALLEL) break
      if (item.state === 'queued' && !running.current.has(item.id)) void run(item)
    }
  }, [items, run])

  const upload = useCallback(
    (files: FileList | File[], target: UploadTarget) => {
      if (!perms.canUpload) {
        toast(ru.common.noRights)
        return
      }
      const accepted: Item[] = []
      for (const file of Array.from(files)) {
        if (!ALLOWED.includes(extension(file.name))) {
          toast(`${file.name}: ${ru.files.unsupported}`)
        } else if (file.size > MAX_BYTES) {
          toast(`${file.name}: ${ru.files.tooBig}`)
        } else if (file.size === 0) {
          toast(`${file.name}: ${ru.files.failed}`)
        } else {
          accepted.push({ id: crypto.randomUUID(), file, target, loaded: 0, state: 'queued' })
        }
      }
      if (accepted.length) setItems((list) => [...list, ...accepted])
    },
    [perms.canUpload],
  )

  const cancel = (item: Item) => {
    controllers.current.get(item.id)?.abort()
    if (item.duplicate) void cancelUpload(item.duplicate.uploadId)
    setItems((list) => list.filter((i) => i.id !== item.id))
  }

  const duplicate = items.find((i) => i.state === 'duplicate')
  const value = useMemo(() => ({ items, upload }), [items, upload])

  return (
    <Ctx.Provider value={value}>
      {children}
      <DropLayer onDrop={upload} />
      <Tray items={items} onCancel={cancel} />
      {duplicate?.duplicate && (
        <Suspense fallback={null}>
          <DuplicateDialog
            name={duplicate.file.name}
            info={duplicate.duplicate.info}
            onSkip={() => cancel(duplicate)}
            onAdd={() => void run(duplicate, { uploadId: duplicate.duplicate!.uploadId, force: true })}
          />
        </Suspense>
      )}
    </Ctx.Provider>
  )
}

/** Перетаскивание файлов с компьютера: подсвечивает зону под курсором и принимает бросок. */
function DropLayer({ onDrop }: { onDrop: Api['upload'] }) {
  const [dragging, setDragging] = useState(false)
  const [overZone, setOverZone] = useState(false)
  const depth = useRef(0)
  const active = useRef<Element | null>(null)

  useEffect(() => {
    const setActive = (el: Element | null) => {
      if (active.current === el) return
      active.current?.removeAttribute('data-drop-active')
      el?.setAttribute('data-drop-active', 'true')
      active.current = el
      setOverZone(!!el)
    }
    const zone = (e: DragEvent) => (e.target instanceof Element ? e.target.closest('[data-drop]') : null)

    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth.current += 1
      setDragging(true)
    }
    const over = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault() // иначе браузер откроет файл в этой же вкладке
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
      setActive(zone(e))
    }
    const leave = () => {
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) {
        setDragging(false)
        setActive(null)
      }
    }
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      const el = zone(e)
      depth.current = 0
      setDragging(false)
      setActive(null)
      const files = e.dataTransfer?.files
      if (!files?.length) return
      if (!el) {
        toast(ru.files.dropNowhere)
        return
      }
      onDrop(files, JSON.parse(el.getAttribute('data-drop') ?? '{}') as UploadTarget)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [onDrop])

  return (
    <AnimatePresence>
      {dragging && (
        <fm.div
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: motion.fast }}
          className="pointer-events-none fixed inset-2 z-[60] flex items-start justify-center rounded-2xl border-2 border-dashed border-brass bg-brass/5"
        >
          <span className="mt-6 rounded-full border border-brass bg-chart px-5 py-2 text-sm font-semibold text-brass-light">
            {overZone ? ru.files.drop : ru.files.dropHint}
          </span>
        </fm.div>
      )}
    </AnimatePresence>
  )
}

function Tray({ items, onCancel }: { items: Item[]; onCancel: (i: Item) => void }) {
  const visible = items.filter((i) => i.state !== 'duplicate')
  if (!visible.length) return null
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-3 bottom-[76px] z-[55] max-h-[40dvh] space-y-2 overflow-y-auto rounded-xl border border-line bg-chart p-3 shadow-2xl shadow-black/50 lg:inset-x-auto lg:bottom-4 lg:right-4 lg:w-[360px]"
    >
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-fog">
        {ru.files.uploading(visible.filter((i) => i.state !== 'done').length)}
      </div>
      {visible.map((item) => {
        const pct = Math.round((item.loaded / item.file.size) * 100)
        return (
          <div key={item.id} className="space-y-1.5">
            <div className="flex items-center gap-2 text-sm">
              {item.state === 'done' ? (
                <Check size={16} className="shrink-0 text-status-done" />
              ) : item.state === 'error' ? (
                <TriangleAlert size={16} className="shrink-0 text-alert" />
              ) : (
                <Loader2 size={16} className="shrink-0 animate-spin text-brass" />
              )}
              <span className="min-w-0 flex-1 truncate">{item.file.name}</span>
              <span className="mono shrink-0 text-xs text-fog">{formatSize(item.file.size)}</span>
              {item.state !== 'done' && (
                <button
                  type="button"
                  onClick={() => onCancel(item)}
                  aria-label={ru.files.cancel}
                  className="flex min-h-touch min-w-touch items-center justify-center rounded text-fog hover:text-paper"
                >
                  <X size={16} />
                </button>
              )}
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-ink">
              <div
                className={cn('h-full rounded-full transition-[width] duration-fast', item.state === 'error' ? 'bg-alert' : 'bg-brass')}
                style={{ width: `${item.state === 'done' ? 100 : pct}%` }}
              />
            </div>
            <div className="text-xs text-fog">
              {item.state === 'retrying' && ru.files.retrying}
              {item.state === 'error' && item.error}
              {item.state === 'queued' && ru.common.loading}
              {item.state === 'uploading' && `${pct}%`}
              {item.state === 'done' && ru.files.done}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Кнопки «Добавить файлы» и (на телефоне) «Снять». Выбор из Telegram — этап 2. */
export function UploadButtons({ target, className }: { target: UploadTarget; className?: string }) {
  const { upload } = useUploads()
  const perms = usePerms()
  const files = useRef<HTMLInputElement>(null)
  const camera = useRef<HTMLInputElement>(null)
  if (!perms.canUpload) return null
  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) upload(e.target.files, target)
    e.target.value = ''
  }
  return (
    <div className={cn('flex flex-wrap gap-2', className)}>
      <input ref={files} type="file" multiple accept={ACCEPT} className="sr-only" tabIndex={-1} onChange={onPick} aria-label={ru.files.chooseFiles} />
      <input ref={camera} type="file" accept="image/*,video/*" capture="environment" className="sr-only" tabIndex={-1} onChange={onPick} aria-label={ru.files.camera} />
      <Button type="button" variant="outline" onClick={() => files.current?.click()}>
        <Plus size={18} />
        {ru.files.add}
      </Button>
      <Button type="button" variant="ghost" className="lg:hidden" onClick={() => camera.current?.click()}>
        <Camera size={18} />
        {ru.files.camera}
      </Button>
    </div>
  )
}
