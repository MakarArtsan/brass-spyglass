import { FILM, TEAM_LOGO, TEAM_NAME } from '@/brand'
import { cn } from '@/lib/utils'

/** Подзорная труба — знак проекта; логотип команды подставится из TEAM_LOGO. */
export function Logo({ className, withTeam = true }: { className?: string; withTeam?: boolean }) {
  return (
    <div className={cn('flex items-center gap-3', className)}>
      {TEAM_LOGO ? (
        <img src={TEAM_LOGO} alt={TEAM_NAME} className="h-10 w-10 rounded-lg object-cover" />
      ) : (
        <svg viewBox="0 0 64 64" className="h-10 w-10 shrink-0 text-brass" aria-hidden fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 38 44 22l5 10-32 16z" />
          <path d="M44 22l8-4M49 32l7-3" />
          <circle cx="20" cy="46" r="3" fill="currentColor" />
        </svg>
      )}
      <div className="min-w-0 leading-tight">
        <div className="truncate font-display text-xl font-semibold">{FILM.titleEn}</div>
        {withTeam && <div className="truncate text-xs text-fog">{TEAM_NAME}</div>}
      </div>
    </div>
  )
}
