import { LogOut, Moon, Sun } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { useLogout } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import type { User } from '@/lib/api'
import { ru } from '@/ru'

/** Карточка текущего участника, переключатель темы и выход. */
export function UserMenu({ user }: { user: User }) {
  const { theme, toggle } = useTheme()
  const logout = useLogout()
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Avatar user={user} className="h-10 w-10" />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-sm font-semibold">{user.name}</div>
          <div className="truncate text-xs text-fog">
            {ru.roles[user.role]}
            {user.tg_username ? ` · @${user.tg_username}` : ''}
          </div>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="default" className="flex-1" onClick={toggle}>
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          {theme === 'dark' ? ru.header.themeLight : ru.header.themeDark}
        </Button>
        <Button variant="ghost" size="icon" onClick={() => logout.mutate()} aria-label={ru.header.logout} title={ru.header.logout}>
          <LogOut size={18} />
        </Button>
      </div>
    </div>
  )
}
