import { NavLink } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { UserMenu } from '@/components/UserMenu'
import type { Abilities, User } from '@/lib/api'
import { visibleNav, type NavItem } from '@/nav'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

export function NavRow({ item, onClick }: { item: NavItem; onClick?: () => void }) {
  return (
    <NavLink
      to={item.path}
      end={item.path === '/'}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          'group relative flex min-h-touch items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors duration-fast',
          isActive ? 'bg-chart text-brass-light' : 'text-fog hover:bg-chart/60 hover:text-paper',
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden
            className={cn('absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-brass transition-opacity duration-fast', isActive ? 'opacity-100' : 'opacity-0')}
          />
          <item.icon size={18} className="shrink-0" />
          <span className="truncate">{item.label}</span>
        </>
      )}
    </NavLink>
  )
}

interface NavGroupsProps {
  abilities: Abilities
  onNavigate?: () => void
  /** Пункты нижней панели телефона в листе «Ещё» не повторяем. */
  skipPhoneItems?: boolean
  columns?: 1 | 2
}

export function NavGroups({ abilities, onNavigate, skipPhoneItems = false, columns = 1 }: NavGroupsProps) {
  const items = visibleNav(abilities).filter((i) => !(skipPhoneItems && i.phone))
  return (
    <>
      {(['main', 'service'] as const).map((group) => (
        <div key={group} className="flex flex-col gap-0.5">
          <div className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-fog/70">
            {group === 'main' ? ru.nav.main : ru.nav.service}
          </div>
          <div className={cn('grid gap-0.5', columns === 2 && 'grid-cols-2')}>
            {items
              .filter((i) => i.group === group)
              .map((item) => (
                <NavRow key={item.path} item={item} onClick={onNavigate} />
              ))}
          </div>
        </div>
      ))}
    </>
  )
}

/** Левый сайдбар ПК-раскладки (от 1024 px). */
export function Sidebar({ user, abilities }: { user: User; abilities: Abilities }) {
  return (
    <aside className="sticky top-0 hidden h-dvh w-[264px] shrink-0 flex-col border-r border-line bg-ink lg:flex">
      <div className="border-b border-line px-5 py-5">
        <Logo />
      </div>
      <nav aria-label={ru.app.name} className="flex flex-1 flex-col gap-2 overflow-y-auto px-3 py-2">
        <NavGroups abilities={abilities} />
      </nav>
      <div className="border-t border-line p-4">
        <UserMenu user={user} />
      </div>
    </aside>
  )
}
