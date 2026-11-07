import { ArrowLeft, ArrowRight, ImagePlus, ImageOff, Loader2, Wand2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { MAX_PHOTOS, MAX_TITLE, MIN_PHOTOS, useCreateCollage } from '@/lib/collages'
import { formatSize } from '@/lib/format'
import { toast } from '@/lib/toast'
import { cancelUpload, DuplicateError, uploadFile } from '@/lib/uploader'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const IMAGE_NAME = /\.(jpe?g|jfif|jpe|png|webp|heic|heif|avif|gif|bmp|tiff?)$/i

interface Item {
  key: string
  file: File
  preview: string
  broken: boolean
  status: 'idle' | 'uploading' | 'done' | 'error'
  progress: number
  fileId?: number
}

let counter = 0

const isPhoto = (file: File) => file.type.startsWith('image/') || IMAGE_NAME.test(file.name)

/** Новый коллаж: выбрать фото (до 10), расставить по порядку, назвать и собрать. Фото загружаются обычным
 * способом, без сжатия, и остаются файлами проекта; повторно загружать уже загруженное не нужно. */
export function CollageForm() {
  const [items, setItems] = useState<Item[]>([])
  const [title, setTitle] = useState('')
  const [phase, setPhase] = useState<'idle' | 'uploading' | 'building'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const picker = useRef<HTMLInputElement>(null)
  const abort = useRef<AbortController | null>(null)
  const create = useCreateCollage()
  const busy = phase !== 'idle'

  useEffect(() => () => abort.current?.abort(), [])
  const previews = useRef<string[]>([])
  useEffect(
    () => () => {
      previews.current.forEach((url) => URL.revokeObjectURL(url))
    },
    [],
  )

  const patch = (key: string, change: Partial<Item>) =>
    setItems((list) => list.map((item) => (item.key === key ? { ...item, ...change } : item)))

  const add = (list: FileList | null) => {
    if (!list || list.length === 0) return
    const photos = Array.from(list).filter((file) => {
      if (isPhoto(file)) return true
      toast(ru.collages.notPhoto(file.name))
      return false
    })
    const room = MAX_PHOTOS - items.length
    if (photos.length > room) toast(ru.collages.tooMany(MAX_PHOTOS))
    const taken = photos.slice(0, Math.max(0, room)).map<Item>((file) => {
      const preview = URL.createObjectURL(file)
      previews.current.push(preview)
      return { key: `p${++counter}`, file, preview, broken: false, status: 'idle', progress: 0 }
    })
    setItems((old) => [...old, ...taken])
    setError(null)
    if (picker.current) picker.current.value = ''
  }

  const remove = (key: string) => setItems((list) => list.filter((item) => item.key !== key))
  const move = (index: number, by: -1 | 1) =>
    setItems((list) => {
      const next = [...list]
      ;[next[index], next[index + by]] = [next[index + by], next[index]]
      return next
    })

  const ready = items.length >= MIN_PHOTOS && title.trim() !== '' && !busy

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!ready) return
    setError(null)
    setPhase('uploading')
    const controller = new AbortController()
    abort.current = controller
    const ids: number[] = []
    for (const item of items) {
      let id = item.fileId
      if (id === undefined) {
        patch(item.key, { status: 'uploading', progress: 0 })
        try {
          const done = await uploadFile(
            item.file,
            { noCompress: true, purpose: 'reference' },
            {
              onProgress: (loaded, total) => patch(item.key, { progress: total ? loaded / total : 0 }),
              onState: () => undefined,
              signal: controller.signal,
            },
          )
          id = done.file.id
        } catch (e) {
          if (e instanceof DuplicateError) {
            void cancelUpload(e.uploadId) // такое фото в проекте уже есть: берём его, не загружая заново
            id = e.info.file_id
          } else if (e instanceof DOMException) {
            setPhase('idle')
            return
          } else {
            patch(item.key, { status: 'error' })
            setError(e instanceof ApiError ? e.message : ru.collages.uploadFailed(item.file.name))
            setPhase('idle')
            return
          }
        }
        patch(item.key, { status: 'done', progress: 1, fileId: id })
      }
      if (ids.includes(id)) {
        patch(item.key, { status: 'error' })
        setError(ru.collages.sameTwice(item.file.name))
        setPhase('idle')
        return
      }
      ids.push(id)
    }
    setPhase('building')
    create.mutate(
      { title: title.trim(), file_ids: ids },
      {
        onSuccess: (made) => {
          toast(ru.collages.made(made.title))
          setItems([])
          setTitle('')
          setPhase('idle')
        },
        onError: (e) => {
          setError(e instanceof ApiError ? e.message : ru.common.saveFailed)
          setPhase('idle')
        },
      },
    )
  }

  return (
    <section aria-labelledby="collage-new" className="space-y-4 rounded-2xl border border-line bg-chart/60 p-5">
      <div>
        <h2 id="collage-new" className="text-2xl">
          {ru.collages.newTitle}
        </h2>
        <p className="text-sm text-fog">{ru.collages.newLead(MIN_PHOTOS, MAX_PHOTOS)}</p>
      </div>

      <form onSubmit={submit} className="space-y-4">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            if (!busy) add(e.dataTransfer.files)
          }}
          className={cn(
            'flex flex-col items-center gap-2 rounded-xl border border-dashed p-5 text-center transition-colors duration-fast',
            over ? 'border-brass bg-brass/10' : 'border-line',
          )}
        >
          <ImagePlus size={24} className="text-brass" aria-hidden />
          <p className="text-sm">{ru.collages.drop}</p>
          <Button type="button" variant="outline" disabled={busy || items.length >= MAX_PHOTOS} onClick={() => picker.current?.click()}>
            {ru.collages.pick}
          </Button>
          <input
            ref={picker}
            type="file"
            multiple
            accept="image/*,.heic,.heif,.avif"
            className="sr-only"
            aria-label={ru.collages.pickInput}
            onChange={(e) => add(e.target.files)}
          />
          <p className="text-xs text-fog" aria-live="polite">
            {ru.collages.count(items.length, MAX_PHOTOS)}
          </p>
        </div>

        {items.length > 0 && (
          <ol aria-label={ru.collages.photosLabel} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {items.map((item, index) => (
              <li key={item.key} className="overflow-hidden rounded-xl border border-line bg-ink">
                <div className="relative aspect-[4/3] bg-ink">
                  {item.broken ? (
                    <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-fog">
                      <ImageOff size={22} aria-hidden />
                      <span className="text-[10px]">{ru.collages.noPreview}</span>
                    </div>
                  ) : (
                    <img
                      src={item.preview}
                      alt={item.file.name}
                      className="h-full w-full object-contain"
                      onError={() => patch(item.key, { broken: true })}
                    />
                  )}
                  <span className="mono absolute left-1.5 top-1.5 rounded bg-ink/80 px-1.5 text-xs text-brass">{index + 1}</span>
                  {item.status === 'uploading' && (
                    <div className="absolute inset-x-0 bottom-0 h-1.5 bg-ink/70" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(item.progress * 100)}>
                      <div className="h-full bg-brass transition-[width] duration-base" style={{ width: `${Math.max(4, item.progress * 100)}%` }} />
                    </div>
                  )}
                </div>
                <div className="px-2 pb-1 pt-1.5">
                  <p className="truncate text-xs" title={item.file.name}>
                    {item.file.name}
                  </p>
                  <p className={cn('text-[11px]', item.status === 'error' ? 'text-alert' : 'text-fog')}>
                    {item.status === 'done' ? ru.collages.uploaded : item.status === 'error' ? ru.collages.itemFailed : formatSize(item.file.size)}
                  </p>
                </div>
                <div className="flex items-center justify-between px-1 pb-1">
                  <button
                    type="button"
                    aria-label={ru.collages.moveLeft(item.file.name)}
                    disabled={busy || index === 0}
                    onClick={() => move(index, -1)}
                    className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:text-paper disabled:opacity-30"
                  >
                    <ArrowLeft size={18} aria-hidden />
                  </button>
                  <button
                    type="button"
                    aria-label={ru.collages.moveRight(item.file.name)}
                    disabled={busy || index === items.length - 1}
                    onClick={() => move(index, 1)}
                    className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:text-paper disabled:opacity-30"
                  >
                    <ArrowRight size={18} aria-hidden />
                  </button>
                  <button
                    type="button"
                    aria-label={ru.collages.removePhoto(item.file.name)}
                    disabled={busy}
                    onClick={() => remove(item.key)}
                    className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:text-alert disabled:opacity-30"
                  >
                    <X size={18} aria-hidden />
                  </button>
                </div>
              </li>
            ))}
          </ol>
        )}

        <label className="block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.collages.titleLabel}</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={MAX_TITLE}
            placeholder={ru.collages.titlePlaceholder}
            disabled={busy}
            className="min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-base text-paper outline-none focus:border-brass"
          />
          <span className="mt-1 block text-xs text-fog">{ru.collages.titleHint}</span>
        </label>

        {error && (
          <p role="alert" className="text-sm text-alert">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="lg" disabled={!ready}>
            {busy ? <Loader2 size={18} className="animate-spin" aria-hidden /> : <Wand2 size={18} aria-hidden />}
            {phase === 'uploading' ? ru.collages.uploading : phase === 'building' ? ru.collages.building : ru.collages.build}
          </Button>
          {!busy && items.length > 0 && items.length < MIN_PHOTOS && <span className="text-sm text-fog">{ru.collages.needMore(MIN_PHOTOS)}</span>}
          {phase === 'building' && (
            <span role="status" className="text-sm text-fog">
              {ru.collages.buildingHint}
            </span>
          )}
        </div>
      </form>
    </section>
  )
}
