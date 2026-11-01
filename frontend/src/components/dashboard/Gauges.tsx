import { Link } from 'react-router-dom'
import { arcPath, chartTransition, polar, useAppear } from '@/components/dashboard/chart'
import { Ring, Tile } from '@/components/dashboard/primitives'
import type { DashboardData } from '@/lib/dashboard'
import { timecode } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const focus =
  'rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass'

/** Большое кольцо: готовые секунды фильма; рядом три малых — шоты, ассеты, задачи в «Готово». */
export function Readiness({ data }: { data: DashboardData['readiness'] }) {
  const small = [
    { key: 'shots', to: '/shots?status=done', value: data.shots },
    { key: 'assets', to: '/assets?status=done', value: data.assets },
    { key: 'tasks', to: '/tasks?status=done', value: data.tasks },
  ] as const
  return (
    <Tile title={ru.dash.readiness}>
      <div className="flex flex-col items-center gap-x-6 gap-y-4 sm:flex-row">
        <Link
          to="/shots"
          className={cn(focus, 'block')}
        >
          <Ring pct={data.pct} size={156} stroke={12} label={`${Math.round(data.pct)}%`}>
            <span className="mono text-3xl font-semibold leading-none">{Math.round(data.pct)}%</span>
            <span className="mono mt-1 text-xs text-fog">{ru.dash.readyOf(timecode(data.ready_sec), timecode(data.shots_sec))}</span>
          </Ring>
          <span className="mt-1.5 block max-w-[156px] text-center text-[11px] leading-tight text-fog">{ru.dash.readySec}</span>
        </Link>
        <ul className="flex w-full flex-1 justify-around gap-2">
          {small.map(({ key, to, value }) => (
            <li key={key}>
              <Link
                to={to}
                className={cn(focus, 'flex min-h-[44px] flex-col items-center gap-1.5 p-1')}
              >
                <Ring pct={value.pct} size={72} stroke={7} tone="stroke-status-done" label={`${Math.round(value.pct)}%`}>
                  <span className="mono text-sm font-semibold">{Math.round(value.pct)}%</span>
                </Ring>
                <span className="text-xs text-fog">{ru.dash.rings[key]}</span>
                <span className="mono text-[11px] text-fog">{ru.dash.ofTotal(value.done, value.total)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </Tile>
  )
}

/** Шкала-спидометр с зелёной зоной 5:00–7:00 и стрелкой текущей суммы по шотам. */
export function RuntimeGauge({ data }: { data: DashboardData['runtime'] }) {
  const appear = useAppear()
  const scale = Math.max(data.max_sec * 1.4, data.shots_sec * 1.1)
  const cx = 100
  const cy = 100
  const r = 78
  const value = appear ? Math.min(1, data.shots_sec / scale) : 0
  const zoneFrom = data.min_sec / scale
  const zoneTo = data.max_sec / scale
  const [minX, minY] = polar(cx, cy, r + 14, 180 - 180 * zoneFrom)
  const [maxX, maxY] = polar(cx, cy, r + 14, 180 - 180 * zoneTo)
  return (
    <Tile title={ru.dash.runtime} to="/scenes">
      <svg viewBox="0 0 200 128" className="mx-auto w-full max-w-[260px]" role="img" aria-label={`${ru.dash.runtime}: ${timecode(data.shots_sec)}`}>
        <path d={arcPath(cx, cy, r, 0, 1)} fill="none" strokeWidth={12} strokeLinecap="round" className="stroke-line" />
        <path d={arcPath(cx, cy, r, zoneFrom, zoneTo)} fill="none" strokeWidth={12} className="stroke-status-done" />
        <g
          className="motion-reduce:transition-none"
          style={{ transform: `rotate(${180 * value}deg)`, transformOrigin: `${cx}px ${cy}px`, transitionProperty: 'transform', ...chartTransition }}
        >
          <line x1={cx - r + 14} y1={cy} x2={cx - 10} y2={cy} strokeWidth={3} strokeLinecap="round" className="stroke-brass" />
        </g>
        <circle cx={cx} cy={cy} r={6} className="fill-brass" />
        <text x={minX} y={minY} textAnchor="end" className="mono fill-fog text-[9px]">{timecode(data.min_sec)}</text>
        <text x={maxX} y={maxY} textAnchor="start" className="mono fill-fog text-[9px]">{timecode(data.max_sec)}</text>
      </svg>
      <div className="-mt-1 text-center">
        <div className="mono text-2xl font-semibold">{timecode(data.shots_sec)}</div>
        <div className={cn('text-xs', data.in_zone ? 'text-status-done' : 'text-alert')}>
          {data.in_zone ? ru.dash.runtimeIn : ru.dash.runtimeOut} · {ru.dash.runtimeZone(timecode(data.min_sec), timecode(data.max_sec))}
        </div>
        <div className="mono mt-0.5 text-[11px] text-fog">{ru.dash.runtimePlan(timecode(data.plan_sec))}</div>
      </div>
    </Tile>
  )
}

/** Полукруг: доля секунд, сделанных в Seedance; цель из правил конкурса отмечена чертой. */
export function SeedanceGauge({ data }: { data: DashboardData['seedance'] }) {
  const appear = useAppear()
  const cx = 100
  const cy = 100
  const r = 78
  const value = appear ? Math.min(1, data.pct / 100) : 0
  const target = data.target_pct / 100
  const [tx1, ty1] = polar(cx, cy, r - 11, 180 - 180 * target)
  const [tx2, ty2] = polar(cx, cy, r + 11, 180 - 180 * target)
  const ok = data.pct >= data.target_pct
  return (
    <Tile title={ru.dash.seedance} to="/shots?tool=seedance">
      <svg viewBox="0 0 200 116" className="mx-auto w-full max-w-[260px]" role="img" aria-label={`${ru.dash.seedance}: ${Math.round(data.pct)}%`}>
        <path d={arcPath(cx, cy, r, 0, 1)} fill="none" strokeWidth={12} strokeLinecap="round" className="stroke-line" />
        <path
          d={arcPath(cx, cy, r, 0, 1)}
          pathLength={1}
          fill="none"
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={1}
          strokeDashoffset={1 - value}
          className={cn(ok ? 'stroke-status-done' : 'stroke-brass', 'transition-[stroke-dashoffset] motion-reduce:transition-none')}
          style={chartTransition}
        />
        <line x1={tx1} y1={ty1} x2={tx2} y2={ty2} strokeWidth={2.5} className="stroke-paper" />
      </svg>
      <div className="-mt-6 text-center">
        <div className="mono text-3xl font-semibold">{Math.round(data.pct)}%</div>
        <div className="mono text-xs text-fog">{ru.dash.seedanceSec(timecode(data.seedance_sec), timecode(data.total_sec))}</div>
        <div className={cn('mt-0.5 text-xs', ok ? 'text-status-done' : 'text-fog')}>{ru.dash.seedanceTarget(data.target_pct)}</div>
      </div>
    </Tile>
  )
}
