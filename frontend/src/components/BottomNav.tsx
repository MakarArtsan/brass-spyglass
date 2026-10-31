import { AnimatePresence, m as fm } from 'framer-motion'
import { MoreHorizontal, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { motion } from '@/brand'
import { NavGroups } from '@/components/Sidebar'
import { UserMenu } from '@/components/UserMenu'
import type { Abilities, User } from '@/lib/api'
import { NAV } from '@/nav'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const PHONE_ITEMS = NAV.filter((i) => i.phone)

function MoreSheet({ user, abilities, onClose }: { user: User; abilities: Abilities; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <fm.div className="fixed inset-0 z-50 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: motion.fast }}>
      <button type="button" tabIndex={-1} aria-hidden className="absolute inset-0 bg-black/60" onClick={onClose} />
      <fm.div
        role="dialog"
        aria-modal="true"
        aria-label={ru.nav.more}
        className="pb-safe absolute inset-x-0 bottom-0 max-h-[85dvh] overflow-y-auto rounded-t-2xl border-t border-line bg-chart"
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ duration: motion.slow, ease: motion.ease }}
        drag="y"
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={{ top: 0, bottom: 0.5 }}
        onDragEnd={(_, info) => info.offset.y > 80 && onClose()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between bg-chart px-4 pb-1 pt-2">
          <span aria-hidden className="mx-auto h-1 w-10 rounded-full bg-line" />
          <button type="button" onClick={onClose} aria-label={ru.nav.close} className="absolute right-2 top-1 flex min-h-touch min-w-touch items-center justify-center text-fog">
            <X size={20} />
          </button>
        </div>
        <nav aria-label={ru.nav.more} className="flex flex-col gap-2 px-3 pb-2">
          <NavGroups abilities={abilities} onNavigate={onClose} skipPhoneItems columns={2} />
        </nav>
        <div className="border-t border-line p-4">
          <UserMenu user={user} />
        </div>
      </fm.div>
    </fm.div>
  )
}

/** Нижняя панель смартфона из 5 пунктов: Дашборд, Шоты, Медиа, Задачи, Ещё. */
export function BottomNav({ user, abilities }: { user: User; abilities: Abilities }) {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const moreActive = !PHONE_ITEMS.some((i) => (i.path === '/' ? pathname === '/' : pathname.startsWith(i.path)))

  const tab = 'flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors duration-fast'
  return (
    <>
      <nav aria-label={ru.app.name} className="pb-safe fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-ink/95 backdrop-blur lg:hidden">
        {PHONE_ITEMS.map((item) => (
          <NavLink key={item.path} to={item.path} end={item.path === '/'} className={({ isActive }) => cn(tab, isActive ? 'text-brass-light' : 'text-fog')}>
            <item.icon size={22} />
            {item.phone}
          </NavLink>
        ))}
        <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" className={cn(tab, moreActive ? 'text-brass-light' : 'text-fog')}>
          <MoreHorizontal size={22} />
          {ru.nav.more}
        </button>
      </nav>
      <AnimatePresence>{open && <MoreSheet user={user} abilities={abilities} onClose={() => setOpen(false)} />}</AnimatePresence>
    </>
  )
}
