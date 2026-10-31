import { FILM } from '@/brand'
import { Countdown } from '@/components/Countdown'
import { StraitMap } from '@/components/StraitMap'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import type { Project } from '@/lib/api'
import { ru } from '@/ru'

/** Шапка: карта пролива на фоне, название фильма и отсчёт до официального срока подачи. */
export function Header({ project }: { project?: Project }) {
  const desktop = useIsDesktop()
  return (
    <header className="pt-safe relative overflow-hidden border-b border-line bg-ink">
      <StraitMap className="absolute inset-0 h-full w-full" />
      <div className="absolute inset-0 bg-gradient-to-r from-ink/90 via-ink/50 to-transparent" aria-hidden />
      <div className="relative flex min-h-[111px] items-center justify-between gap-4 px-4 py-4 lg:min-h-[146px] lg:px-8 lg:py-6">
        <div className="min-w-0">
          <p className="mono truncate text-[10px] uppercase tracking-[0.22em] text-brass lg:text-[11px]">{FILM.titleEn}</p>
          <p className="font-display text-xl font-semibold leading-tight lg:text-4xl">
            {project?.title ?? FILM.title}
          </p>
        </div>
        {project && (
          <Countdown
            target={project.deadline_official}
            label={ru.countdown.official}
            parts={['d', 'h']}
            small={!desktop}
            className="shrink-0 items-end"
          />
        )}
      </div>
    </header>
  )
}
