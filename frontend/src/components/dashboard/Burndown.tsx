import { useAppear, useWidth } from '@/components/dashboard/chart'
import { Tile } from '@/components/dashboard/primitives'
import type { DashboardData } from '@/lib/dashboard'
import { timecode } from '@/lib/format'
import { ru } from '@/ru'

const H = 170
const PAD = { l: 38, r: 12, t: 12, b: 24 }

const dayMonth = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`
const daysBetween = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000)

/** Оставшиеся секунды до готовности против идеальной линии до внутреннего срока и прогноз. */
export function BurndownTile({ data }: { data: DashboardData['burndown'] }) {
  const appear = useAppear()
  const [box, W] = useWidth<HTMLDivElement>()
  const n = data.points.length
  const top = Math.max(data.total_sec, 1)
  const x = (i: number) => PAD.l + (n > 1 ? (i / (n - 1)) * (W - PAD.l - PAD.r) : 0)
  const y = (v: number) => PAD.t + (1 - v / top) * (H - PAD.t - PAD.b)
  const ideal = data.points.map((p, i) => `${x(i).toFixed(1)},${y(p.ideal).toFixed(1)}`).join(' ')
  const known = data.points.flatMap((p, i) => (p.actual === null ? [] : [{ i, v: p.actual }]))
  const actual = known.map((k) => `${x(k.i).toFixed(1)},${y(k.v).toFixed(1)}`).join(' ')
  const last = known[known.length - 1]
  const area = known.length > 1 ? `M ${x(known[0].i)},${y(0)} L ${actual.replaceAll(' ', ' L ')} L ${x(last.i)},${y(0)} Z` : ''
  const deadlineIndex = data.points.findIndex((p) => p.d === data.deadline)
  const forecastIndex = data.forecast ? data.points.findIndex((p) => p.d === data.forecast) : -1

  let verdict: string
  let tone = 'text-fog'
  if (data.remaining_sec <= 0) {
    verdict = ru.dash.forecastDone
    tone = 'text-status-done'
  } else if (!data.forecast) {
    verdict = ru.dash.forecastNone
  } else {
    const late = daysBetween(data.deadline, data.forecast)
    verdict = `${ru.dash.forecast(dayMonth(data.forecast))}, ${late <= 0 ? ru.dash.forecastIn : ru.dash.forecastLate(late)}`
    tone = late <= 0 ? 'text-status-done' : 'text-alert'
  }

  const summary = `${ru.dash.burndown}: ${ru.dash.burndownRemaining(timecode(data.remaining_sec))}. ${verdict}`
  return (
    <Tile title={ru.dash.burndown} to="/shots">
      <div ref={box} className="w-full">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(top * f)} y2={y(top * f)} className="stroke-line" strokeWidth={1} />
            <text x={PAD.l - 5} y={y(top * f) + 3} textAnchor="end" className="mono fill-fog text-[10px]">
              {timecode(top * f)}
            </text>
          </g>
        ))}
        {deadlineIndex >= 0 && (
          <g>
            <line x1={x(deadlineIndex)} x2={x(deadlineIndex)} y1={PAD.t} y2={H - PAD.b} className="stroke-alert" strokeDasharray="2 3" strokeWidth={1} />
            <text x={x(deadlineIndex)} y={H - 8} textAnchor="end" className="mono fill-alert text-[10px]">{dayMonth(data.deadline)}</text>
          </g>
        )}
        <text x={PAD.l} y={H - 8} className="mono fill-fog text-[10px]">{dayMonth(data.points[0].d)}</text>
        <polyline points={ideal} fill="none" className="stroke-fog" strokeWidth={1.5} strokeDasharray="4 3" />
        {area && <path d={area} className="fill-brass" fillOpacity={appear ? 0.15 : 0} style={{ transition: 'fill-opacity 0.25s' }} />}
        {known.length > 1 && (
          <polyline
            points={actual}
            pathLength={1}
            fill="none"
            className="stroke-brass transition-[stroke-dashoffset] motion-reduce:transition-none"
            strokeWidth={2.5}
            strokeLinejoin="round"
            strokeDasharray={1}
            strokeDashoffset={appear ? 0 : 1}
            style={{ transitionDuration: '0.25s' }}
          />
        )}
        {last && <circle cx={x(last.i)} cy={y(last.v)} r={3.5} className="fill-brass" />}
        {last && forecastIndex > last.i && (
          <line x1={x(last.i)} y1={y(last.v)} x2={x(forecastIndex)} y2={y(0)} className="stroke-brass" strokeDasharray="1 4" strokeLinecap="round" strokeWidth={2} />
        )}
      </svg>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fog">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-brass" aria-hidden />{ru.dash.burndownActual}</span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t border-dashed border-fog" aria-hidden />{ru.dash.burndownIdeal}</span>
      </div>
      <p className={`mt-2 text-sm font-medium ${tone}`}>{verdict}</p>
      <p className="mono mt-0.5 text-xs text-fog">
        {ru.dash.burndownRemaining(timecode(data.remaining_sec))}
        {data.pace_sec_per_day > 0 && ` · ${ru.dash.pace(String(data.pace_sec_per_day).replace('.', ','))}`}
      </p>
    </Tile>
  )
}
