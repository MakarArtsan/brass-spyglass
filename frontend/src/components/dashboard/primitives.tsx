import { useEffect, useRef, useState, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { Link } from 'react-router-dom'
import { chartTransition, useAppear } from '@/components/dashboard/chart'
import { cn } from '@/lib/utils'

interface TileProps {
  title: string
  to?: string
  children: ReactNode
  className?: string
  action?: ReactNode
}

/** Плитка дашборда. Если задан `to`, вся плитка — ссылка в отфильтрованный список. */
export function Tile({ title, to, children, className, action }: TileProps) {
  const body = (
    <>
      <div className="mb-3 flex items-start justify-between gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-fog">{title}</h2>
        {action}
      </div>
      {children}
    </>
  )
  const classes = cn('panel block p-4', className)
  if (!to) return <section className={classes}>{body}</section>
  return (
    <section className={cn(classes, 'relative transition-colors hover:border-brass/50 focus-within:border-brass/50')}>
      <Link
        to={to}
        aria-label={title}
        className="absolute inset-0 z-10 rounded-[inherit] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass"
      />
      <div className="relative">{body}</div>
    </section>
  )
}

interface RingProps {
  pct: number
  size: number
  stroke: number
  /** Класс цвета дуги (Tailwind stroke-*). */
  tone?: string
  children?: ReactNode
  label: string
}

/** Кольцо с процентом внутри. */
export function Ring({ pct, size, stroke, tone = 'stroke-brass', children, label }: RingProps) {
  const appear = useAppear()
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const shown = appear ? Math.max(0, Math.min(100, pct)) : 0
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-line" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          className={cn(tone, 'transition-[stroke-dashoffset] motion-reduce:transition-none')}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - shown / 100)}
          style={chartTransition}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  )
}

interface DeferredProps {
  /** Заголовок плитки: до загрузки его читают программы экрана, а рядом нет пустоты для фокуса. */
  title: string
  /** Оценка высоты, чтобы страница не дёргалась, когда плитка дорисуется. */
  minHeight: number
  children: ReactNode
  className?: string
}

/**
 * Плитка под сгибом строится, только когда до неё доскроллили (или нажали Tab). Это убирает с первого
 * показа работу, которую пользователь не видит, и держит основной поток свободным.
 */
export function Deferred({ title, minHeight, children, className }: DeferredProps) {
  const ref = useRef<HTMLElement>(null)
  const [shown, setShown] = useState(() => typeof IntersectionObserver === 'undefined')

  useEffect(() => {
    const el = ref.current
    if (shown || !el) return undefined
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setShown(true)
      },
      { rootMargin: '400px 0px' },
    )
    observer.observe(el)
    // Клавиатура ходит по Tab и не должна перескакивать через плитки, которых ещё нет.
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Tab') flushSync(() => setShown(true))
    }
    window.addEventListener('keydown', onKey)
    return () => {
      observer.disconnect()
      window.removeEventListener('keydown', onKey)
    }
  }, [shown])

  if (shown) return <>{children}</>
  return (
    <section ref={ref} className={cn('panel', className)} style={{ minHeight }} aria-label={title}>
      <h2 className="sr-only">{title}</h2>
    </section>
  )
}
