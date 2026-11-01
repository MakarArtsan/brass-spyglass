import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { toast } from '@/lib/toast'
import { useAddLink } from '@/lib/queries'
import { ru } from '@/ru'

interface Props {
  target?: { entityType: string; entityId: number; purpose: string }
  onClose: () => void
}

/** Ссылка как файл. Сервер сам не пустит внутренние адреса и скажет почему. */
export default function LinkDialog({ target, onClose }: Props) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const add = useAddLink(target)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    add.mutate(url.trim(), {
      onSuccess: (result) => {
        if (!result.created) toast(ru.link.exists)
        onClose()
      },
      onError: (e) => setError(e instanceof ApiError ? e.message : ru.common.saveFailed),
    })
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/60" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[91] w-[min(92vw,480px)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-chart p-6 shadow-2xl outline-none">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="font-display text-2xl">{ru.link.title}</Dialog.Title>
            <Dialog.Close className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.library.close}>
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-fog">{ru.link.lead}</Dialog.Description>
          <form onSubmit={submit} className="mt-4 space-y-3">
            <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-fog">
              {ru.link.url}
              <input
                type="url"
                inputMode="url"
                required
                autoFocus
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={ru.link.placeholder}
                className="mt-1.5 min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-base normal-case tracking-normal text-paper outline-none focus:border-brass"
              />
            </label>
            {error && (
              <p role="alert" className="text-sm text-alert">
                {error}
              </p>
            )}
            <div className="flex justify-end">
              <Button type="submit" disabled={add.isPending || url.trim() === ''}>
                {add.isPending ? ru.link.adding : ru.link.add}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
