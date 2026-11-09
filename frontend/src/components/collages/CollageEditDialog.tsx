import * as Dialog from '@radix-ui/react-dialog'
import { Loader2, Save, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { PhotoGrid, PhotoPicker } from '@/components/collages/PhotoGrid'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import {
  MAX_PHOTOS,
  MAX_TITLE,
  MIN_PHOTOS,
  useCollage,
  useDeleteCollage,
  useUpdateCollage,
  type Collage,
  type CollageDetail,
} from '@/lib/collages'
import { PhotoUploadError, sameIds, savedPhoto, uploadMissing, usePhotoItems } from '@/lib/collagePhotos'
import { toast } from '@/lib/toast'
import { ru } from '@/ru'

interface BodyProps {
  collage: Collage
  detail: CollageDetail
  canDelete: boolean
  busy: boolean
  setBusy: (busy: boolean) => void
  onClose: () => void
}

/** Форма правки. Состав берётся из карточки коллажа один раз, при открытии: дальше его правит человек. */
function EditBody({ collage, detail, canDelete, busy, setBusy, onClose }: BodyProps) {
  const [original] = useState(() => detail.photo_list.map((p) => p.id))
  const { items, patch, add, remove: drop, move } = usePhotoItems(
    detail.photo_list.map((p) => savedPhoto(p.id, p.original_name, p.urls.thumb ?? p.urls.original, p.size_bytes)),
  )
  const update = useUpdateCollage()
  const remove = useDeleteCollage()
  const [title, setTitle] = useState(collage.title)
  const [phase, setPhase] = useState<'idle' | 'uploading' | 'saving'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  const abort = useRef<AbortController | null>(null)
  useEffect(() => () => abort.current?.abort(), [])

  const missing = Math.max(0, collage.photos - detail.photo_list.length)
  const photosChanged = !items.every((i) => i.fileId !== undefined) || !sameIds(items.map((i) => i.fileId ?? -1), original)
  const titleChanged = title.trim() !== collage.title
  const valid = title.trim() !== '' && items.length >= MIN_PHOTOS && items.length <= MAX_PHOTOS
  const canSave = valid && (photosChanged || titleChanged) && !busy

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canSave) return
    setError(null)
    setPhase('uploading')
    setBusy(true)
    const controller = new AbortController()
    abort.current = controller
    let ids: number[]
    try {
      ids = await uploadMissing(items, patch, controller.signal)
    } catch (e) {
      if (!(e instanceof DOMException)) setError(e instanceof PhotoUploadError ? e.message : ru.common.saveFailed)
      setPhase('idle')
      setBusy(false)
      return
    }
    setPhase('saving')
    update.mutate(
      {
        id: collage.id,
        ...(titleChanged && { title: title.trim() }),
        ...(!sameIds(ids, original) && { file_ids: ids }),
      },
      {
        onSuccess: (done) => {
          toast(ru.collages.edited(done.title))
          onClose()
        },
        onError: (e) => {
          setError(e instanceof ApiError ? e.message : ru.common.saveFailed)
          setPhase('idle')
          setBusy(false)
        },
      },
    )
  }

  const rebuilding = phase === 'saving' && photosChanged

  return (
    <>
      <form onSubmit={save} className="space-y-4">
        <label className="block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.collages.titleLabel}</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={MAX_TITLE}
            disabled={busy}
            className="min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-base text-paper outline-none focus:border-brass"
          />
        </label>

        {missing > 0 && <p className="text-xs text-status-in_progress">{ru.collages.editMissing(missing)}</p>}
        <PhotoGrid items={items} busy={busy} onMove={move} onRemove={drop} onBroken={(key) => patch(key, { broken: true })} />
        <PhotoPicker
          count={items.length}
          busy={busy}
          onAdd={(list) => {
            if (add(list)) setError(null)
          }}
          compact
        />
        {items.length < MIN_PHOTOS && <p className="text-sm text-fog">{ru.collages.needMore(MIN_PHOTOS)}</p>}

        {error && (
          <p role="alert" className="text-sm text-alert">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="lg" disabled={!canSave}>
            {busy ? <Loader2 size={18} className="animate-spin" aria-hidden /> : <Save size={18} aria-hidden />}
            {phase === 'uploading' ? ru.collages.uploading : phase === 'saving' ? (rebuilding ? ru.collages.editRebuilding : ru.collages.editSaving) : ru.collages.editSave}
          </Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>
            {ru.collages.editCancel}
          </Button>
          {!photosChanged && !titleChanged && !busy && <span className="text-xs text-fog">{ru.collages.editNothing}</span>}
          {rebuilding && (
            <span role="status" className="text-sm text-fog">
              {ru.collages.buildingHint}
            </span>
          )}
        </div>
      </form>

      {canDelete && (
        <div className="mt-2 border-t border-line pt-4">
          {asking ? (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={ru.collages.deleteAsk(collage.title)}>
              <span className="text-sm">{ru.collages.deleteQuestion}</span>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setBusy(true)
                  remove.mutate(collage.id, {
                    onSuccess: onClose,
                    onError: (e) => {
                      toast(e instanceof ApiError ? e.message : ru.common.saveFailed)
                      setAsking(false)
                      setBusy(false)
                    },
                  })
                }}
              >
                {ru.collages.deleteYes}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setAsking(false)}>
                {ru.collages.deleteNo}
              </Button>
            </div>
          ) : (
            <Button type="button" variant="ghost" disabled={busy} onClick={() => setAsking(true)} aria-label={ru.collages.delete(collage.title)} className="text-alert">
              <Trash2 size={16} aria-hidden />
              {ru.collages.deleteCollage}
            </Button>
          )}
        </div>
      )}
    </>
  )
}

/** Правка готового коллажа: название, состав и порядок фото. Что изменилось, то и уходит на сервер:
 * одно название картинку не пересобирает. Отсюда же коллаж удаляется (с подтверждением). */
export default function CollageEditDialog({ collage, canDelete, onClose }: { collage: Collage; canDelete: boolean; onClose: () => void }) {
  const detail = useCollage(collage.id)
  const [busy, setBusy] = useState(false)
  return (
    <Dialog.Root open onOpenChange={(open) => !open && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/70" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[91] flex max-h-[94dvh] w-[min(96vw,1000px)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-2xl border border-line bg-chart p-4 shadow-2xl outline-none sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="font-display text-2xl">{ru.collages.editTitle(collage.title)}</Dialog.Title>
            <Dialog.Close
              disabled={busy}
              className="flex min-h-touch min-w-touch shrink-0 items-center justify-center rounded-full text-fog hover:text-paper disabled:opacity-40"
              aria-label={ru.collages.close}
            >
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="text-sm text-fog">{ru.collages.editLead(MIN_PHOTOS, MAX_PHOTOS)}</Dialog.Description>
          {detail.isPending && <p className="text-sm text-fog">{ru.collages.editLoading}</p>}
          {detail.isError && (
            <p role="alert" className="text-sm text-alert">
              {ru.collages.loadFailed}
            </p>
          )}
          {detail.data && <EditBody collage={collage} detail={detail.data} canDelete={canDelete} busy={busy} setBusy={setBusy} onClose={onClose} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
