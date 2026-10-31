import { MoreHorizontal } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import type { Abilities, User } from '@/lib/api'
import { NAV } from '@/nav'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

// Лист «Ещё» (framer-motion) грузится отдельным чанком при первом нажатии (и заранее, в простое).
const MoreSheetHost = lazy(() => import('@/components/MoreSheetHost'))

const PHONE_ITEMS = NAV.filter((i) => i.phone)

/** Нижняя панель смартфона из 5 пунктов: Дашборд, Шоты, Медиа, Задачи, Ещё. */
export function BottomNav({ user, abilities }: { user: User; abilities: Abilities }) {
  const [open, setOpen] = useState(false)
  const [opened, setOpened] = useState(false) // после первого открытия лист остаётся смонтирован: нужен для плавного ухода
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
        <button type="button" onClick={() => {
            setOpened(true)
            setOpen(true)
          }}
          aria-haspopup="dialog" className={cn(tab, moreActive ? 'text-brass-light' : 'text-fog')}>
          <MoreHorizontal size={22} />
          {ru.nav.more}
        </button>
      </nav>
      {opened && (
        <Suspense fallback={null}>
          <MoreSheetHost open={open} user={user} abilities={abilities} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  )
}
