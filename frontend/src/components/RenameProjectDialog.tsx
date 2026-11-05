import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { useRenameProject } from '@/hooks/useAuth'
import { ApiError, type Project } from '@/lib/api'
import { ru } from '@/ru'

const INPUT =
  'mt-1.5 min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-base normal-case tracking-normal text-paper outline-none focus:border-brass'

/** Переименование проекта: русское и английское название. Только для владельца (кнопку прячет интерфейс,
 * право проверяет сервер). Адрес проекта остаётся прежним. */
export default function RenameProjectDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const [title, setTitle] = useState(project.title)
  const [titleEn, setTitleEn] = useState(project.title_en)
  const [error, setError] = useState<string | null>(null)
  const rename = useRenameProject()

  const changed = title.trim() !== project.title || titleEn.trim() !== project.title_en
  const valid = title.trim() !== '' && titleEn.trim() !== ''

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    rename.mutate(
      {
        ...(title.trim() !== project.title && { title: title.trim() }),
        ...(titleEn.trim() !== project.title_en && { title_en: titleEn.trim() }),
      },
      { onSuccess: onClose, onError: (e) => setError(e instanceof ApiError ? e.message : ru.common.saveFailed) },
    )
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/60" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[91] w-[min(92vw,480px)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-chart p-6 shadow-2xl outline-none">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="font-display text-2xl">{ru.projectRename.title}</Dialog.Title>
            <Dialog.Close
              className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper"
              aria-label={ru.projectRename.close}
            >
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-fog">{ru.projectRename.lead}</Dialog.Description>
          <form onSubmit={submit} className="mt-4 space-y-3">
            <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-fog">
              {ru.projectRename.titleRu}
              <input
                required
                autoFocus
                maxLength={200}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className={INPUT}
              />
            </label>
            <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-fog">
              {ru.projectRename.titleEn}
              <input required maxLength={200} value={titleEn} onChange={(e) => setTitleEn(e.target.value)} className={INPUT} />
            </label>
            {error && (
              <p role="alert" className="text-sm text-alert">
                {error}
              </p>
            )}
            <div className="flex justify-end">
              <Button type="submit" disabled={rename.isPending || !changed || !valid}>
                {rename.isPending ? ru.projectRename.saving : ru.projectRename.save}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
