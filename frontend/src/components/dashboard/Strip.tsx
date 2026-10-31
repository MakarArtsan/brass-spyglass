import { Link } from 'react-router-dom'
import { chartTransition, useAppear, useWidth } from '@/components/dashboard/chart'
import { Tile } from '@/components/dashboard/primitives'
import type { DashboardData } from '@/lib/dashboard'
import { ru } from '@/ru'

/** 12 сцен в порядке трекера: ширина — длительность, заливка — готовность. */
export function FilmStrip({ scenes }: { scenes: DashboardData['film_strip'] }) {
  const appear = useAppear()
  return (
    <Tile title={ru.dash.strip}>
      {/* Минимум 44 px на сцену: на телефоне полоса прокручивается, а не сжимает цель касания. */}
      <ol className="flex gap-1 overflow-x-auto pb-1">
        {scenes.map((s) => (
          <li key={s.scene_id} style={{ flex: `${s.planned_sec} 1 0`, minWidth: 44 }}>
            <Link
              to={`/scenes/${s.scene_id}`}
              aria-label={ru.dash.stripScene(s.number, s.title, Math.round(s.ready_pct))}
              title={ru.dash.stripScene(s.number, s.title, Math.round(s.ready_pct))}
              className="relative flex h-14 flex-col justify-between overflow-hidden rounded-md border border-line bg-ink p-1.5 transition-colors hover:border-brass/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brass"
            >
              <span
                aria-hidden
                className="absolute inset-x-0 bottom-0 bg-status-done/40 transition-[height] motion-reduce:transition-none"
                style={{ height: appear ? `${s.ready_pct}%` : 0, ...chartTransition }}
              />
              <span className="mono relative text-xs font-semibold">{s.number}</span>
              <span className="mono relative text-[10px] text-paper">{s.planned_sec}{ru.common.sec}</span>
            </Link>
          </li>
        ))}
      </ol>
    </Tile>
  )
}

const H = 130
const PAD = { l: 20, r: 10, t: 10, b: 22 }

/** Уровень барабана по сценам, от 0 до 5; сцены без уровня остаются разрывом линии. */
export function DrumCurve({ scenes }: { scenes: DashboardData['drum'] }) {
  const [box, W] = useWidth<HTMLDivElement>()
  const n = scenes.length
  const x = (i: number) => PAD.l + (n > 1 ? (i / (n - 1)) * (W - PAD.l - PAD.r) : 0)
  const y = (level: number) => PAD.t + (1 - level / 5) * (H - PAD.t - PAD.b)
  let path = ''
  let pen = false
  scenes.forEach((s, i) => {
    if (s.level === null) {
      pen = false
      return
    }
    path += `${pen ? 'L' : 'M'} ${x(i).toFixed(1)} ${y(s.level).toFixed(1)} `
    pen = true
  })
  return (
    <Tile title={ru.dash.drum} to="/scenes">
      <div ref={box} className="w-full">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ru.dash.drumSummary}>
        {[0, 1, 2, 3, 4, 5].map((l) => (
          <g key={l}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(l)} y2={y(l)} className="stroke-line" strokeWidth={1} />
            <text x={PAD.l - 5} y={y(l) + 3} textAnchor="end" className="mono fill-fog text-[10px]">{l}</text>
          </g>
        ))}
        {path && <path d={path} fill="none" className="stroke-brass" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />}
        {scenes.map((s, i) => (
          <g key={s.scene_id}>
            {s.level !== null && <circle cx={x(i)} cy={y(s.level)} r={3.5} className="fill-brass" />}
            <text x={x(i)} y={H - 6} textAnchor="middle" className="mono fill-fog text-[10px]">{s.number}</text>
          </g>
        ))}
      </svg>
      </div>
    </Tile>
  )
}
