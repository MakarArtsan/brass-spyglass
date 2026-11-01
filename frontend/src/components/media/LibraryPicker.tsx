import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useState } from 'react'
import { LibraryView } from '@/components/media/LibraryView'
import { Button } from '@/components/ui/button'
import { useAttachFromLibrary } from '@/lib/queries'
import { toast } from '@/lib/toast'
import { ApiError } from '@/lib/api'
import type { LibraryItem } from '@/lib/types'
import { ru } from '@/ru'

interface Props {
  entityType: string
  entityId: number
  /** Назначение, с которым файлы привяжутся по умолчанию. */
  purpose: string
  onClose: () => void
}

/** «Файл из медиатеки — на шот или ассет»: привязка без повторной загрузки (ТЗ). */
export default function LibraryPicker({ entityType, entityId, purpose, onClose }: Props) {
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [chosen, setChosen] = useState(purpose)
  const attach = useAttachFromLibrary(entityType, entityId)

  const toggle = (item: LibraryItem) =>
    setPicked((cur) => {
      const next = new Set(cur)
      if (next.has(item.id)) next.delete(item.id)
      else next.add(item.id)
      return next
    })

  const submit = () =>
    attach.mutate(
      { fileIds: [...picked], purpose: chosen },
      {
        onSuccess: () => {
          toast(ru.library.attached)
          onClose()
        },
        onError: (e) => toast(e instanceof ApiError ? e.message : ru.common.saveFailed),
      },
    )

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/60" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[91] flex h-[min(90dvh,760px)] w-[min(96vw,920px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl border border-line bg-chart shadow-2xl outline-none">
          <div className="flex items-start justify-between gap-3 border-b border-line p-4">
            <div>
              <Dialog.Title className="font-display text-2xl">{ru.library.pickTitle}</Dialog.Title>
              <Dialog.Description className="text-sm text-fog">{ru.library.pickHint}</Dialog.Description>
            </div>
            <Dialog.Close className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.library.close}>
              <X size={18} />
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <LibraryView mode="picker" selected={picked} onPick={toggle} />
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line p-4">
            <label className="flex items-center gap-2 text-sm text-fog">
              {ru.library.purpose}
              <select value={chosen} onChange={(e) => setChosen(e.target.value)} className="min-h-touch rounded-lg border border-line bg-ink px-2 text-paper">
                {Object.entries(ru.purpose).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <Button type="button" onClick={submit} disabled={picked.size === 0 || attach.isPending}>
              {ru.library.attach(picked.size)}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
