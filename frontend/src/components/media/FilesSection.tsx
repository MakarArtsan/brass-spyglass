import { Images, Link2, Send } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { FileTile } from '@/components/media/FileTile'
import { dropZone, UploadButtons } from '@/components/Uploads'
import { usePerms } from '@/hooks/usePerms'
import { useEntityFiles, useFileMutations } from '@/lib/queries'
import type { FileItem } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

// Окно просмотра (плееры, wavesurfer) тяжёлое — грузим при первом открытии файла.
const TelegramWindow = lazy(() => import('@/components/telegram/TelegramWindow'))
const LibraryPicker = lazy(() => import('@/components/media/LibraryPicker'))
const LinkDialog = lazy(() => import('@/components/media/LinkDialog'))
const VersionsDialog = lazy(() => import('@/components/media/VersionsDialog'))
const MediaViewer = lazy(() => import('@/components/media/MediaViewer').then((m) => ({ default: m.MediaViewer })))

interface Props {
  title: string
  entityType: string
  entityId: number
  /** Какие назначения показывать в этой секции. */
  purposes: string[]
  /** С каким назначением загружать сюда новые файлы. */
  uploadPurpose: string
  className?: string
  /** id текущей версии финального файла карточки (у сцены и шота). */
  finalId?: number | null
  /** Выбрать файл финальным или снять выбор (null). Есть только у тех, кому можно править карточку. */
  onSetFinal?: (fileId: number | null) => void
}

/** Файлы карточки одного назначения: плитки в рамке-линзе, загрузка кнопкой и перетаскиванием. */
export function FilesSection({ title, entityType, entityId, purposes, uploadPurpose, className, finalId, onSetFinal }: Props) {
  const perms = usePerms()
  const { data } = useEntityFiles(entityType, entityId)
  const mutations = useFileMutations(entityType, entityId)
  const [open, setOpen] = useState<number | null>(null)
  const [versionsOf, setVersionsOf] = useState<FileItem | null>(null)
  const [dialog, setDialog] = useState<'library' | 'link' | 'telegram' | null>(null)
  const items = (data ?? []).filter((a) => purposes.includes(a.purpose))
  // Ссылки открываются в новой вкладке, в окне просмотра листаются только файлы.
  const viewable = items.filter((a) => a.file.kind !== 'link')
  const openItem = (item: (typeof items)[number]) => {
    if (item.file.kind === 'link') {
      if (item.file.url) window.open(item.file.url, '_blank', 'noopener,noreferrer')
      return
    }
    setOpen(viewable.indexOf(item))
  }
  const zone = dropZone({ entityType, entityId, purpose: uploadPurpose })

  return (
    <section className={cn('rounded-xl border border-dashed border-line p-3', className)} {...(perms.canUpload ? zone : {})} aria-label={title}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="flex-1 font-sans text-xs font-semibold uppercase tracking-[0.14em] text-fog">{title}</h3>
        <UploadButtons target={{ entityType, entityId, purpose: uploadPurpose }} />
        {perms.canUpload && (
          <>
            <button type="button" onClick={() => setDialog('telegram')} className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border border-line px-3 text-sm text-fog hover:border-brass/60 hover:text-paper">
              <Send size={16} aria-hidden />
              {ru.tg.button}
            </button>
            <button type="button" onClick={() => setDialog('library')} className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border border-line px-3 text-sm text-fog hover:border-brass/60 hover:text-paper">
              <Images size={16} aria-hidden />
              {ru.library.fromLibrary}
            </button>
            <button type="button" onClick={() => setDialog('link')} className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border border-line px-3 text-sm text-fog hover:border-brass/60 hover:text-paper">
              <Link2 size={16} aria-hidden />
              {ru.link.title}
            </button>
          </>
        )}
      </div>
      {items.length === 0 ? (
        <p className="py-3 text-center text-sm text-fog">{perms.canUpload ? ru.shots.dragFiles : ru.files.noFiles}</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {items.map((a) => (
            <FileTile
              key={a.attachment_id}
              item={a}
              onOpen={() => openItem(a)}
              onVersions={() => setVersionsOf(a.file)}
              isFinal={finalId != null && a.file.id === finalId}
              onFinal={onSetFinal ? () => onSetFinal(finalId === a.file.id ? null : a.file.id) : undefined}
              onDetach={
                perms.canUpload && (perms.meId === a.attached_by?.id || perms.role === 'owner' || perms.role === 'director')
                  ? () => mutations.detach.mutate(a.attachment_id)
                  : undefined
              }
              onDelete={
                perms.canDelete({ uploaded_by: a.file.uploaded_by })
                  ? () => window.confirm(ru.files.deleteConfirm) && mutations.remove.mutate(a.file.id)
                  : undefined
              }
            />
          ))}
        </div>
      )}
      {open != null && (
        <Suspense fallback={null}>
          <MediaViewer files={viewable.map((a) => a.file)} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />
        </Suspense>
      )}
      {versionsOf && (
        <Suspense fallback={null}>
          <VersionsDialog file={versionsOf} onClose={() => setVersionsOf(null)} />
        </Suspense>
      )}
      {dialog === 'library' && (
        <Suspense fallback={null}>
          <LibraryPicker entityType={entityType} entityId={entityId} purpose={uploadPurpose} onClose={() => setDialog(null)} />
        </Suspense>
      )}
      {dialog === 'telegram' && (
        <Suspense fallback={null}>
          <TelegramWindow entityType={entityType} entityId={entityId} purpose={uploadPurpose} onClose={() => setDialog(null)} />
        </Suspense>
      )}
      {dialog === 'link' && (
        <Suspense fallback={null}>
          <LinkDialog target={{ entityType, entityId, purpose: uploadPurpose }} onClose={() => setDialog(null)} />
        </Suspense>
      )}
    </section>
  )
}
