import { lazy, Suspense, useState } from 'react'
import { FileTile } from '@/components/media/FileTile'
import { dropZone, UploadButtons } from '@/components/Uploads'
import { usePerms } from '@/hooks/usePerms'
import { useEntityFiles, useFileMutations } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

// Окно просмотра (плееры, wavesurfer) тяжёлое — грузим при первом открытии файла.
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
}

/** Файлы карточки одного назначения: плитки в рамке-линзе, загрузка кнопкой и перетаскиванием. */
export function FilesSection({ title, entityType, entityId, purposes, uploadPurpose, className }: Props) {
  const perms = usePerms()
  const { data } = useEntityFiles(entityType, entityId)
  const mutations = useFileMutations(entityType, entityId)
  const [open, setOpen] = useState<number | null>(null)
  const items = (data ?? []).filter((a) => purposes.includes(a.purpose))
  const zone = dropZone({ entityType, entityId, purpose: uploadPurpose })

  return (
    <section className={cn('rounded-xl border border-dashed border-line p-3', className)} {...(perms.canUpload ? zone : {})} aria-label={title}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="flex-1 font-sans text-xs font-semibold uppercase tracking-[0.14em] text-fog">{title}</h3>
        <UploadButtons target={{ entityType, entityId, purpose: uploadPurpose }} />
      </div>
      {items.length === 0 ? (
        <p className="py-3 text-center text-sm text-fog">{perms.canUpload ? ru.shots.dragFiles : ru.files.noFiles}</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {items.map((a, i) => (
            <FileTile
              key={a.attachment_id}
              item={a}
              onOpen={() => setOpen(i)}
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
          <MediaViewer files={items.map((a) => a.file)} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />
        </Suspense>
      )}
    </section>
  )
}
