import * as Dialog from '@radix-ui/react-dialog'
import { Upload, X } from 'lucide-react'
import { useRef } from 'react'
import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { ACCEPT, useUploads } from '@/components/Uploads'
import { usePerms } from '@/hooks/usePerms'
import { ApiError } from '@/lib/api'
import { displayName } from '@/lib/files'
import { formatDateTime } from '@/lib/format'
import { useFileVersions, useRollback } from '@/lib/queries'
import { toast } from '@/lib/toast'
import type { FileItem } from '@/lib/types'
import { ru } from '@/ru'

interface Props {
  file: FileItem
  onClose: () => void
}

/** История версий файла: v3, v2, v1 — с автором и датой; откат одной кнопкой; загрузка новой версии. */
export default function VersionsDialog({ file, onClose }: Props) {
  const perms = usePerms()
  const { upload } = useUploads()
  const { data: versions } = useFileVersions(file.id)
  const rollback = useRollback()
  const input = useRef<HTMLInputElement>(null)

  const pick = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files?.length) {
      upload(event.target.files, { versionOf: file.id })
      onClose()
    }
    event.target.value = ''
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/60" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[91] max-h-[86vh] w-[min(94vw,520px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-line bg-chart p-6 shadow-2xl outline-none">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="font-display text-2xl">{ru.files.versionsTitle}</Dialog.Title>
            <Dialog.Close className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.library.close}>
              <X size={20} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-fog">{displayName(file)}. {ru.files.versionsLead}</Dialog.Description>

          <ol className="mt-4 space-y-2" aria-label={ru.files.versionsTitle}>
            {(versions ?? []).map((v) => (
              <li key={v.id} className="flex items-center gap-3 rounded-xl border border-line bg-ink/40 p-3">
                <span className="mono w-9 shrink-0 text-center text-sm font-semibold text-brass">{ru.files.versionBadge(v.version_no)}</span>
                {v.uploaded_by && <Avatar user={v.uploaded_by} className="h-8 w-8" />}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{v.original_name}</div>
                  <div className="truncate text-xs text-fog">{ru.files.versionBy(v.uploaded_by?.name ?? ru.journal.system, formatDateTime(v.uploaded_at))}</div>
                </div>
                {v.is_current ? (
                  <span className="rounded-full border border-brass/50 px-2.5 py-0.5 text-xs font-semibold text-brass">{ru.files.versionCurrent}</span>
                ) : (
                  perms.canUpload && (
                    <Button
                      variant="outline"
                      disabled={rollback.isPending}
                      onClick={() =>
                        rollback.mutate(v.id, {
                          onSuccess: () => toast(ru.files.rolledBack(v.version_no)),
                          onError: (e) => toast(e instanceof ApiError ? e.message : ru.common.saveFailed),
                        })
                      }
                    >
                      {ru.files.rollback}
                    </Button>
                  )
                )}
              </li>
            ))}
            {versions?.length === 0 && <li className="text-sm text-fog">{ru.files.noVersions}</li>}
          </ol>

          {perms.canUpload && (
            <div className="mt-5">
              <input ref={input} type="file" accept={ACCEPT} className="sr-only" onChange={pick} aria-label={ru.files.newVersion} tabIndex={-1} />
              <Button onClick={() => input.current?.click()}>
                <Upload size={16} aria-hidden />
                {ru.files.newVersion}
              </Button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
