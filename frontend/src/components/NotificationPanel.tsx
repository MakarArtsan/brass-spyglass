import * as Dialog from '@radix-ui/react-dialog'
import { MessageSquare, Paperclip, Layers, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Avatar } from '@/components/Avatar'
import { useNotifications, useReadAll, useReadNotification, type NotificationItem } from '@/lib/notifications'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const relative = new Intl.RelativeTimeFormat('ru-RU', { numeric: 'auto' })
const absolute = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

function ago(iso: string): string {
  const minutes = Math.round((new Date(iso).getTime() - Date.now()) / 60_000)
  if (minutes > -1) return 'только что'
  if (minutes > -60) return relative.format(minutes, 'minute')
  if (minutes > -60 * 24) return relative.format(Math.round(minutes / 60), 'hour')
  return absolute.format(new Date(iso))
}

const ICON = { comment: MessageSquare, file: Paperclip, version: Layers } as const

function sentence(item: NotificationItem): string {
  return ru.notifications[item.kind](item.count)
}

function Row({ item, onOpen }: { item: NotificationItem; onOpen: (item: NotificationItem) => void }) {
  const Icon = ICON[item.kind]
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(item)}
        className={cn(
          'flex min-h-touch w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left outline-none transition-colors duration-fast hover:bg-ink focus-visible:ring-2 focus-visible:ring-brass',
          !item.read && 'bg-brass/10',
        )}
      >
        {item.actor ? <Avatar user={item.actor} className="h-9 w-9" /> : <span className="h-9 w-9 shrink-0 rounded-full bg-line" aria-hidden />}
        <span className="min-w-0 flex-1">
          <span className="block text-sm leading-snug">
            <span className="font-semibold">{item.actor?.name ?? ru.notifications.system}</span> {sentence(item)}{' '}
            <span className="text-brass">{ru.notifications.on(item.label ?? ru.notifications.card)}</span>
          </span>
          {item.snippet && <span className="mt-0.5 block truncate text-xs text-fog">«{item.snippet}»</span>}
          <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-fog">
            <Icon size={12} aria-hidden />
            {ago(item.created_at)}
          </span>
        </span>
        {!item.read && (
          <span className="mt-2 flex items-center" aria-label={ru.notifications.unread}>
            <span className="h-2.5 w-2.5 rounded-full bg-brass" aria-hidden />
          </span>
        )}
      </button>
    </li>
  )
}

/** Список уведомлений: прочитанное гаснет, клик ведёт в карточку, «Прочитать все» снимает счётчик. */
export default function NotificationPanel({ onClose }: { onClose: () => void }) {
  const { data, isError } = useNotifications()
  const read = useReadNotification()
  const readAll = useReadAll()
  const navigate = useNavigate()

  const open = (item: NotificationItem) => {
    if (!item.read) read.mutate(item.id)
    onClose()
    navigate(item.url)
  }

  return (
    <Dialog.Root open onOpenChange={(value) => !value && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/40" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed right-3 top-[calc(env(safe-area-inset-top)+72px)] z-[91] flex max-h-[min(78vh,640px)] w-[min(94vw,440px)] flex-col rounded-2xl border border-line bg-chart shadow-2xl shadow-black/50 outline-none"
        >
          <div className="flex items-center gap-2 border-b border-line px-4 py-2">
            <Dialog.Title className="flex-1 font-display text-xl">{ru.notifications.title}</Dialog.Title>
            {(data?.unread ?? 0) > 0 && (
              <button
                type="button"
                onClick={() => readAll.mutate()}
                className="min-h-touch rounded-lg px-2 text-sm text-brass hover:text-brass-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass"
              >
                {ru.notifications.readAll}
              </button>
            )}
            <Dialog.Close aria-label={ru.library.close} className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper">
              <X size={20} />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {isError ? (
              <p className="p-4 text-sm text-alert" role="alert">
                {ru.notifications.loadFailed}
              </p>
            ) : data && data.items.length === 0 ? (
              <div className="p-6 text-center">
                <p className="font-display text-xl">{ru.notifications.empty}</p>
                <p className="mt-1 text-sm text-fog">{ru.notifications.emptyLead}</p>
              </div>
            ) : (
              <ul className="space-y-1" aria-label={ru.notifications.title}>
                {data?.items.map((item) => <Row key={item.id} item={item} onOpen={open} />)}
              </ul>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
