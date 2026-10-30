import { useMemo } from 'react'
import { cn } from '@/lib/utils'

type Variant = 'header' | 'page'

/** header — низкая полоса для шапки (якорь справа), page — весь экран (экран входа). */
const VARIANTS = {
  header: { w: 1200, h: 150, step: 20, soundings: 8, rose: 0.85, island: 0.9, align: 'xMaxYMid' },
  page: { w: 1200, h: 800, step: 27, soundings: 34, rose: 1.4, island: 1.7, align: 'xMidYMid' },
} as const

/** Детерминированный «случай»: карта не должна меняться при каждой отрисовке. */
function seeded(seed: number) {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296
    return s / 4294967296
  }
}

/** Линия глубины: плавная волна, у каждой своя фаза. */
function contour(i: number, w: number, y0: number): string {
  const amp = 4 + (i % 3) * 3
  const pts: string[] = []
  for (let x = 0; x <= w; x += 15) {
    const y = y0 + Math.sin(x / 140 + i * 1.3) * amp + Math.sin(x / 47 + i) * 2.5
    pts.push(`${x === 0 ? 'M' : 'L'}${x},${y.toFixed(1)}`)
  }
  return pts.join(' ')
}

/**
 * Карта пролива — фон шапки: линии глубин, промеры, роза ветров и силуэт третьего острова
 * на горизонте (пасхалка из фильма). Всё рисуется цветами токенов, поэтому работает в обеих темах.
 */
export function StraitMap({ className, variant = 'header' }: { className?: string; variant?: Variant }) {
  const v = VARIANTS[variant]
  const horizon = v.h * 0.84
  const { lines, soundings } = useMemo(() => {
    const rnd = seeded(7)
    return {
      lines: Array.from({ length: Math.floor((v.h - 10) / v.step) }, (_, i) => contour(i, v.w, 12 + i * v.step)),
      soundings: Array.from({ length: v.soundings }, () => ({
        x: Math.round(40 + rnd() * (v.w - 80)),
        y: Math.round(18 + rnd() * (horizon - 30)),
        t: String(Math.round(4 + rnd() * 34)),
      })),
    }
  }, [v, horizon])

  return (
    <svg
      viewBox={`0 0 ${v.w} ${v.h}`}
      preserveAspectRatio={`${v.align} slice`}
      className={cn('pointer-events-none select-none', className)}
      aria-hidden
      focusable="false"
    >
      <g fill="none" stroke="rgb(var(--fog))" strokeWidth="1">
        {lines.map((d, i) => (
          <path key={i} d={d} opacity={0.14 + (i % 3) * 0.04} strokeDasharray={i % 4 === 3 ? '2 6' : undefined} />
        ))}
      </g>

      <g className="mono" fill="rgb(var(--fog))" fontSize="10" opacity="0.45">
        {soundings.map((s, i) => (
          <text key={i} x={s.x} y={s.y}>
            {s.t}
          </text>
        ))}
      </g>

      {/* Горизонт и третий остров */}
      <line x1="0" y1={horizon} x2={v.w} y2={horizon} stroke="rgb(var(--fog))" strokeOpacity="0.28" />
      <g transform={`translate(${v.w * 0.52} ${horizon}) scale(${v.island})`}>
        <path
          d="M0,0 C16,-14 28,-10 40,-22 C48,-30 56,-21 68,-25 L73,-42 L77,-25 C92,-27 106,-10 134,0 Z"
          fill="rgb(var(--chart))"
          stroke="rgb(var(--fog))"
          strokeOpacity="0.55"
        />
        <path d="M-10,8 H120 M-24,15 H100" stroke="rgb(var(--fog))" strokeOpacity="0.2" strokeLinecap="round" />
      </g>

      {/* Роза ветров */}
      <g transform={`translate(${v.w * 0.8} ${v.h * 0.46}) scale(${v.rose})`} opacity="0.6">
        <circle r="46" fill="none" stroke="rgb(var(--brass))" strokeOpacity="0.5" />
        <circle r="31" fill="none" stroke="rgb(var(--brass))" strokeOpacity="0.35" strokeDasharray="2 4" />
        <path d="M0,-44 L6,0 L0,44 L-6,0 Z M-44,0 L0,-6 L44,0 L0,6 Z" fill="rgb(var(--brass))" fillOpacity="0.34" />
        <path
          d="M-22,-22 L0,-4 L22,-22 L4,0 L22,22 L0,4 L-22,22 L-4,0 Z"
          fill="rgb(var(--brass))"
          fillOpacity="0.2"
        />
        <text y="-52" textAnchor="middle" fontSize="12" fontWeight="700" fill="rgb(var(--brass))" className="mono">
          N
        </text>
      </g>
    </svg>
  )
}
