import { Bell } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { useNotifications } from '@/lib/notifications'
import { ru } from '@/ru'

// Сам список подгружается при первом открытии: на первый показ нужен только колокольчик.
const NotificationPanel = lazy(() => import('@/components/NotificationPanel'))

/** Колокольчик в шапке: число непрочитанного; нажатие открывает список, клик по строке ведёт в карточку. */
export function NotificationBell() {
  const { data } = useNotifications()
  const [open, setOpen] = useState(false)
  const unread = data?.unread ?? 0
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={ru.notifications.bell(unread)}
        aria-haspopup="dialog"
        className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-line bg-ink/60 text-paper outline-none hover:border-brass focus-visible:ring-2 focus-visible:ring-brass"
      >
        <Bell size={20} aria-hidden />
        {unread > 0 && (
          <span
            aria-hidden
            className="mono absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-alert px-1 text-[10px] font-bold text-ink"
          >
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <Suspense fallback={null}>
          <NotificationPanel onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  )
}
