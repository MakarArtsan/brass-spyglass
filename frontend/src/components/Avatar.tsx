import { cn, initials } from '@/lib/utils'
import type { User } from '@/lib/api'

interface Props {
  user: Pick<User, 'id' | 'name' | 'color' | 'has_avatar'>
  className?: string
}

/** Аватар из Telegram; без него — инициалы на цвете участника. */
export function Avatar({ user, className }: Props) {
  return (
    <span
      className={cn(
        'inline-flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full text-xs font-bold text-ink ring-2 ring-ink',
        className,
      )}
      style={{ backgroundColor: user.color }}
      title={user.name}
    >
      {user.has_avatar ? (
        <img src={`/api/users/${user.id}/avatar`} alt={user.name} className="h-full w-full object-cover" />
      ) : (
        <span aria-hidden>{initials(user.name)}</span>
      )}
    </span>
  )
}
