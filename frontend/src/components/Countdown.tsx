import { COUNTDOWN } from '@/brand'
import { useNow } from '@/hooks/useNow'
import { cn, pad2 } from '@/lib/utils'
import { ru } from '@/ru'

type Part = 'd' | 'h' | 'm' | 's'
const UNITS: Record<Part, string> = {
  d: ru.countdown.days,
  h: ru.countdown.hours,
  m: ru.countdown.minutes,
  s: ru.countdown.seconds,
}

function Flip({ value, small }: { value: string; small: boolean }) {
  return (
    <span
      className={cn(
        'relative inline-flex overflow-hidden rounded-md border border-brass/50 bg-chart',
        'after:absolute after:inset-x-0 after:top-1/2 after:h-px after:bg-ink/70',
        small ? 'h-9 min-w-[2.4rem] px-1.5 text-xl' : 'h-14 min-w-[3.6rem] px-2 text-3xl',
      )}
    >
      {/* Новое значение — новый элемент: цифра «перекидывается» CSS-анимацией, без библиотеки. */}
      <span key={value} className="mono m-auto font-semibold leading-none motion-safe:animate-flip-in">
        {value}
      </span>
    </span>
  )
}

export interface CountdownProps {
  target: string
  label: string
  parts?: Part[]
  small?: boolean
  className?: string
}

/** Дни : часы : минуты : секунды. Латунный за 7 дней до срока, красный за 3. */
export function Countdown({ target, label, parts = ['d', 'h', 'm', 's'], small = false, className }: CountdownProps) {
  const now = useNow(parts.includes('s') ? 1000 : 15_000)
  const diff = Math.max(0, new Date(target).getTime() - now)
  const daysLeft = diff / 86_400_000
  const tone = daysLeft <= COUNTDOWN.alertDays ? 'alert' : daysLeft <= COUNTDOWN.brassDays ? 'brass' : 'paper'

  const sec = Math.floor(diff / 1000)
  const value: Record<Part, number> = {
    d: Math.floor(sec / 86_400),
    h: Math.floor(sec / 3600) % 24,
    m: Math.floor(sec / 60) % 60,
    s: sec % 60,
  }
  const spoken = `${label}: ${value.d} ${ru.countdown.days} ${value.h} ${ru.countdown.hours}`

  return (
    <div className={cn('flex flex-col gap-1.5', className)} data-tone={tone}>
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-fog">{label}</span>
      <div
        role="timer"
        aria-label={diff === 0 ? ru.countdown.passed : spoken}
        className={cn(
          'flex items-end gap-1.5',
          tone === 'alert' && 'text-alert',
          tone === 'brass' && 'text-brass',
          tone === 'paper' && 'text-paper',
        )}
      >
        {parts.map((p) => (
          <span key={p} className="flex flex-col items-center gap-1">
            <Flip value={p === 'd' && value.d > 99 ? String(value.d) : pad2(value[p])} small={small} />
            <span className="text-[10px] uppercase tracking-wider text-fog">{UNITS[p]}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
