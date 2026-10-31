import { Tile } from '@/components/dashboard/primitives'
import type { DashboardData, DashPerson } from '@/lib/dashboard'
import { ru } from '@/ru'

const CELL = 11
const GAP = 3
const MIN_WEEKS = 14

/** Понедельник = 0: неделя в российской раскладке. */
const weekday = (iso: string) => (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7
const dayMonth = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`

function Heatmap({ days }: { days: DashboardData['activity']['heatmap'] }) {
  const lead = weekday(days[0]?.d ?? '1970-01-05')
  const weeks = Math.max(MIN_WEEKS, Math.ceil((days.length + lead) / 7))
  const offset = weeks - Math.ceil((days.length + lead) / 7) // дополняем слева пустыми неделями
  const max = Math.max(1, ...days.map((d) => d.n))
  const total = days.reduce((a, d) => a + d.n, 0)
  const step = CELL + GAP
  return (
    <svg
      viewBox={`0 0 ${weeks * step - GAP} ${7 * step - GAP}`}
      className="w-full"
      style={{ maxWidth: weeks * 20 }}
      role="img"
      aria-label={ru.dash.heatmapSummary(days.length, total)}
    >
      {days.map((day, i) => {
        const slot = i + lead
        const x = (Math.floor(slot / 7) + offset) * step
        const y = (slot % 7) * step
        const level = day.n === 0 ? 0 : Math.ceil((4 * day.n) / max)
        return (
          <rect
            key={day.d}
            x={x}
            y={y}
            width={CELL}
            height={CELL}
            rx={2}
            className={level === 0 ? 'fill-fog' : 'fill-brass'}
            fillOpacity={level === 0 ? 0.16 : [0, 0.3, 0.5, 0.75, 1][level]}
          >
            <title>{`${dayMonth(day.d)}: ${day.n}`}</title>
          </rect>
        )
      })}
    </svg>
  )
}

function Bars({ bars, people }: { bars: DashboardData['activity']['bars']; people: Record<string, DashPerson> }) {
  const totals = bars.map((b) => Object.values(b.by_user).reduce((a, n) => a + n, 0))
  const max = Math.max(1, ...totals)
  const seen = new Map<string, DashPerson>()
  for (const bar of bars) for (const id of Object.keys(bar.by_user)) if (people[id]) seen.set(id, people[id])
  return (
    <div>
      <ol className="flex h-[88px] items-end gap-1" aria-label={ru.dash.activityBars}>
        {bars.map((bar, i) => {
          const summary = ru.dash.activityDay(dayMonth(bar.d), bar.uploads, bar.statuses, bar.comments)
          return (
            <li key={bar.d} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={summary} aria-label={summary}>
              <div className="flex flex-col-reverse overflow-hidden rounded-t-sm" style={{ height: `${(totals[i] / max) * 100}%` }}>
                {Object.entries(bar.by_user).map(([id, n]) => (
                  <span key={id} style={{ flexGrow: n, backgroundColor: people[id]?.color }} className={people[id] ? undefined : 'bg-fog'} />
                ))}
              </div>
              <span className={totals[i] === 0 ? 'h-px bg-line' : 'hidden'} />
            </li>
          )
        })}
      </ol>
      <ol className="mt-1 flex gap-1" aria-hidden>
        {bars.map((bar, i) => (
          <li key={bar.d} className="mono min-w-0 flex-1 text-center text-[9px] text-fog">
            {i % 2 === 0 ? bar.d.slice(8) : ''}
          </li>
        ))}
      </ol>
      {seen.size > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-fog">
          {[...seen.values()].map((p) => (
            <li key={p.id} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: p.color }} aria-hidden />
              {p.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Тепловая карта за весь проект (как на GitHub) и столбики за 14 дней, окрашенные цветами участников. */
export function ActivityTile({
  data,
  people,
  to,
}: {
  data: DashboardData['activity']
  people: Record<string, DashPerson>
  /** Журнал недоступен гостю: у него плитка без ссылки. */
  to?: string
}) {
  return (
    <Tile title={ru.dash.activity} to={to}>
      <div className="grid gap-5 md:grid-cols-2">
        <div>
          <p className="mb-2 text-xs text-fog">{ru.dash.activityHeatmap}</p>
          <Heatmap days={data.heatmap} />
        </div>
        <div>
          <p className="mb-2 text-xs text-fog">{ru.dash.activityBars}</p>
          <Bars bars={data.bars} people={people} />
        </div>
      </div>
    </Tile>
  )
}
