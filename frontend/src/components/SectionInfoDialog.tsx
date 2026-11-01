import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { NAV } from '@/nav'
import { ru } from '@/ru'

/** Справка о разделе: одно предложение «зачем» и список «что здесь можно». */
export default function SectionInfoDialog({ path, onClose }: { path: string; onClose: () => void }) {
  const label = NAV.find((item) => item.path === path)?.label ?? ''
  const text = ru.info.sections[path]
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/60" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 z-[91] max-h-[86vh] w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-line bg-chart p-6 shadow-2xl outline-none"
        >
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="font-display text-3xl leading-tight">{ru.info.title(label)}</Dialog.Title>
            <Dialog.Close className="flex min-h-touch min-w-touch shrink-0 items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.library.close}>
              <X size={20} />
            </Dialog.Close>
          </div>
          <h3 className="mt-4 font-sans text-xs font-semibold uppercase tracking-[0.14em] text-brass">{ru.info.why}</h3>
          <p className="mt-1.5 leading-relaxed">{text.why}</p>
          <h3 className="mt-5 font-sans text-xs font-semibold uppercase tracking-[0.14em] text-brass">{ru.info.can}</h3>
          <ul className="mt-2 space-y-2">
            {text.can.map((line) => (
              <li key={line} className="flex gap-2.5 text-sm leading-relaxed text-paper/90">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brass" aria-hidden />
                <span>{line}</span>
              </li>
            ))}
          </ul>
          <div className="mt-6 flex justify-end">
            <Button onClick={onClose}>{ru.info.close}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
