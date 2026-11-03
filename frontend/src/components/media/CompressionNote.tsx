import { RotateCcw } from 'lucide-react'
import { usePerms } from '@/hooks/usePerms'
import { ApiError } from '@/lib/api'
import { displayName } from '@/lib/files'
import { formatDate, formatSize } from '@/lib/format'
import { useRestoreOriginal } from '@/lib/queries'
import { toast } from '@/lib/toast'
import type { FileItem } from '@/lib/types'
import { ru } from '@/ru'

/** Итог сжатия картинки в карточке файла: «2,4 МБ → 610 КБ, −75%» и «Вернуть оригинал» (7 дней). */
export function CompressionNote({ file, onUpdated }: { file: FileItem; onUpdated: (file: FileItem) => void }) {
  const perms = usePerms()
  const restore = useRestoreOriginal()
  const c = file.compression
  if (file.kind !== 'image') return null

  let text: string | null = null
  if (c.state === 'done' && c.original_size_bytes && file.size_bytes != null) {
    const delta = Math.round(100 * (1 - file.size_bytes / c.original_size_bytes))
    text = ru.files.compressionSaved(formatSize(c.original_size_bytes), formatSize(file.size_bytes), delta)
  } else if (c.state === 'small_gain') text = ru.files.compressionSmallGain
  else if (c.no_compress) text = ru.files.compressionNone
  const canRestore = c.can_restore && perms.canDelete({ uploaded_by: file.uploaded_by })
  if (!text && !canRestore) return null

  const onRestore = () => {
    if (!window.confirm(ru.files.restoreConfirm(displayName(file)))) return
    restore.mutate(file.id, {
      onSuccess: (updated) => {
        onUpdated(updated)
        toast(ru.files.restored)
      },
      onError: (e) => toast(e instanceof ApiError ? e.message : ru.common.saveFailed),
    })
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 text-xs text-fog" data-testid="compression-note">
      {text && <span className="mono">{text}</span>}
      {canRestore && c.original_until && <span>{ru.files.originalUntil(formatDate(c.original_until))}</span>}
      {canRestore && (
        <button
          type="button"
          onClick={onRestore}
          disabled={restore.isPending}
          className="inline-flex min-h-touch items-center gap-1.5 rounded-lg px-1 text-brass hover:text-brass-light disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass"
        >
          <RotateCcw size={14} aria-hidden />
          {ru.files.restoreOriginal}
        </button>
      )}
    </div>
  )
}
