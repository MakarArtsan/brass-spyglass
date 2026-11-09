import { Loader2, Wand2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { PhotoGrid, PhotoPicker } from '@/components/collages/PhotoGrid'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { MAX_PHOTOS, MAX_TITLE, MIN_PHOTOS, useCreateCollage } from '@/lib/collages'
import { PhotoUploadError, uploadMissing, usePhotoItems } from '@/lib/collagePhotos'
import { toast } from '@/lib/toast'
import { ru } from '@/ru'

/** Новый коллаж: выбрать фото (до 10), расставить по порядку, назвать и собрать. Фото загружаются обычным
 * способом, без сжатия, и остаются файлами проекта; повторно загружать уже загруженное не нужно. */
export function CollageForm() {
  const { items, setItems, patch, add, remove, move } = usePhotoItems()
  const [title, setTitle] = useState('')
  const [phase, setPhase] = useState<'idle' | 'uploading' | 'building'>('idle')
  const [error, setError] = useState<string | null>(null)
  const abort = useRef<AbortController | null>(null)
  const create = useCreateCollage()
  const busy = phase !== 'idle'

  useEffect(() => () => abort.current?.abort(), [])

  const ready = items.length >= MIN_PHOTOS && title.trim() !== '' && !busy

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!ready) return
    setError(null)
    setPhase('uploading')
    const controller = new AbortController()
    abort.current = controller
    let ids: number[]
    try {
      ids = await uploadMissing(items, patch, controller.signal)
    } catch (e) {
      if (!(e instanceof DOMException)) setError(e instanceof PhotoUploadError ? e.message : ru.common.saveFailed)
      setPhase('idle')
      return
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
        <PhotoPicker
          count={items.length}
          busy={busy}
          onAdd={(list) => {
            if (add(list)) setError(null)
          }}
        />
        <PhotoGrid items={items} busy={busy} onMove={move} onRemove={remove} onBroken={(key) => patch(key, { broken: true })} />

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
