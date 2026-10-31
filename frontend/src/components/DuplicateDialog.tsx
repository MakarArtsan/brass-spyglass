import * as Dialog from '@radix-ui/react-dialog'
import { Button } from '@/components/ui/button'
import type { DuplicateInfo } from '@/lib/types'
import { ru } from '@/ru'

interface Props {
  name: string
  info: DuplicateInfo
  onSkip: () => void
  onAdd: () => void
}

/** «Этот файл уже добавлял Петя в шот 04.02 — всё равно добавить?» (ТЗ). */
export default function DuplicateDialog({ name, info, onSkip, onAdd }: Props) {
  return (
    <Dialog.Root open>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/60" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-[91] w-[min(92vw,440px)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-chart p-6 shadow-2xl outline-none"
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
        >
          <Dialog.Title className="font-display text-2xl">{ru.files.duplicateTitle}</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-fog">
            {ru.files.duplicateText(info.uploaded_by ?? ru.journal.system, info.attached_to.join(', '))}
          </Dialog.Description>
          <p className="mono mt-3 truncate text-xs text-fog">{name}</p>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <Button variant="outline" onClick={onSkip}>
              {ru.files.skip}
            </Button>
            <Button onClick={onAdd}>{ru.files.addAnyway}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
