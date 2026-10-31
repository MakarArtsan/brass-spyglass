import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Avatar } from '@/components/Avatar'
import { Tile } from '@/components/dashboard/primitives'
import type { DashboardData, DashFeedItem, DashPerson } from '@/lib/dashboard'
import { describe } from '@/lib/activity'
import { formatDate, formatDateTime, formatGiB } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const focus =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass'

export function MediaTile({ data }: { data: DashboardData['media'] }) {
  const { storage } = data
  return (
    <Tile title={ru.dash.media} to="/library">
      <div className="flex items-baseline justify-between gap-3">
        <span className="mono text-3xl font-semibold">{data.total}</span>
        <span className="text-xs text-fog">{ru.dash.mediaFromTelegram(data.from_telegram)}</span>
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {(Object.keys(ru.dash.kindsPlural) as (keyof typeof ru.dash.kindsPlural)[]).map((kind) => (
          <li key={kind} className="flex justify-between gap-2 text-fog">
            <span>{ru.dash.kindsPlural[kind]}</span>
            <span className="mono text-paper">{data.by_kind[kind]}</span>
          </li>
        ))}
      </ul>
      <div className="mt-4">
        <div className="flex items-baseline justify-between text-xs text-fog">
          <span>{ru.dash.disk}</span>
          <span className="mono">{ru.dash.diskOf(formatGiB(storage.used_bytes), formatGiB(storage.limit_bytes))}</span>
        </div>
        <div
          className="mt-1.5 h-2 overflow-hidden rounded-full bg-line"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(storage.used_pct)}
          aria-label={ru.dash.disk}
        >
          <div
            className={cn('h-full rounded-full transition-[width] duration-200 motion-reduce:transition-none', storage.warn ? 'bg-alert' : 'bg-brass')}
            style={{ width: `${Math.min(100, storage.used_pct)}%` }}
          />
        </div>
        {storage.warn && (
          <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-alert">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {storage.full ? ru.dash.diskFull : ru.dash.diskWarn}
          </p>
        )}
      </div>
    </Tile>
  )
}

function AlertRow({ to, title, count, detail }: { to: string; title: string; count: number; detail?: string }) {
  const bad = count > 0
  return (
    <li>
      <Link to={to} className={cn(focus, 'flex min-h-[44px] items-start gap-2.5 rounded-lg px-1 py-1.5 transition-colors hover:bg-ink/60')}>
        {bad ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-alert" aria-hidden /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-status-done" aria-hidden />}
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2 text-sm">
            <span>{title}</span>
            <span className={cn('mono font-semibold', bad ? 'text-alert' : 'text-fog')}>{count}</span>
          </span>
          {detail && <span className="mono mt-0.5 block truncate text-xs text-fog">{detail}</span>}
        </span>
      </Link>
    </li>
  )
}

const preview = (items: string[]) => (items.length > 6 ? `${items.slice(0, 6).join(', ')} · ${ru.dash.more(items.length - 6)}` : items.join(', '))

export function AlertsTile({ data }: { data: DashboardData['alerts'] }) {
  const overdueDetail = Object.entries(data.overdue.by_type)
    .filter(([, n]) => n > 0)
    .map(([type, n]) => `${ru.dash.entityPlural[type] ?? type} ${n}`)
    .join(', ')
  const total = data.overdue.total + data.long_shots.length + data.orphan_assets.length + data.scenes_without_final.length
  return (
    <Tile title={ru.dash.alerts}>
      <ul className="-mx-1">
        <AlertRow to="/tasks?overdue=1" title={ru.dash.alertOverdue} count={data.overdue.total} detail={overdueDetail} />
        <AlertRow to="/shots?long=1" title={ru.dash.alertLong} count={data.long_shots.length} detail={preview(data.long_shots.map((s) => s.code))} />
        <AlertRow to="/assets?orphans=1" title={ru.dash.alertOrphans} count={data.orphan_assets.length} detail={preview(data.orphan_assets.map((a) => a.code))} />
        <AlertRow to="/scenes?nofinal=1" title={ru.dash.alertNoFinal} count={data.scenes_without_final.length} />
      </ul>
      {total === 0 && <p className="mt-1 text-sm text-status-done">{ru.dash.alertsOk}</p>}
    </Tile>
  )
}

function entityLink(type: string, id: number | null): string {
  if (id === null) return '/'
  switch (type) {
    case 'shot': return `/shots?shot=${id}`
    case 'scene': return `/scenes/${id}`
    case 'asset': return `/assets?asset=${id}`
    case 'file': return `/library?file=${id}`
    case 'setup_payoff': return '/setups'
    case 'sound_cue': return '/sound'
    case 'task': return '/tasks'
    default: return '/'
  }
}

function FeedRow({ item }: { item: DashFeedItem }) {
  const { kind, details } = describe({ ...item, diff: item.diff })
  const body = (
    <span className="flex min-h-[44px] items-center gap-3 rounded-lg px-1 py-1.5 transition-colors hover:bg-ink/60">
      {item.actor ? <Avatar user={item.actor} className="h-7 w-7 text-[10px]" /> : <span className="h-7 w-7 shrink-0" />}
      <span className="min-w-0 flex-1 text-sm leading-snug">
        <span className="font-medium">{item.actor?.name ?? ru.common.dash}</span>
        <span className="text-fog"> · {kind}</span>
        {item.label && <span> · {item.label}</span>}
        {details.length > 0 && <span className="mono block truncate text-xs text-fog">{details.join('; ')}</span>}
        <span className="mono block text-[11px] text-fog">{formatDateTime(item.at)}</span>
      </span>
      {item.thumb_url && (
        <img src={item.thumb_url} alt="" width={40} height={40} loading="lazy" className="h-10 w-10 shrink-0 rounded-full border border-brass/60 object-cover" />
      )}
    </span>
  )
  return (
    <li>
      <Link to={entityLink(item.entity_type, item.entity_id)} className={cn(focus, 'block rounded-lg')}>
        {body}
      </Link>
    </li>
  )
}

/** Последние действия команды с превью файлов. Обновляется вживую (SSE). */
export function FeedTile({ items, hidden }: { items: DashFeedItem[]; hidden: boolean }) {
  return (
    <Tile title={ru.dash.feed}>
      {hidden ? (
        <p className="text-sm text-fog">{ru.dash.feedHidden}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-fog">{ru.dash.feedEmpty}</p>
      ) : (
        <ul className="-mx-1">{items.map((item) => <FeedRow key={item.id} item={item} />)}</ul>
      )}
    </Tile>
  )
}

export function MyTasksTile({ tasks }: { tasks: DashboardData['my_tasks'] }) {
  return (
    <Tile title={ru.dash.myTasks} to="/tasks?mine=1">
      {tasks.length === 0 ? (
        <p className="text-sm text-fog">{ru.dash.myTasksEmpty}</p>
      ) : (
        <ul className="space-y-1.5">
          {tasks.map((t) => (
            <li key={t.id} className="text-sm">
              <span className="flex items-baseline gap-2">
                <span className="mono w-12 shrink-0 text-xs text-fog">{t.code}</span>
                <span className="min-w-0 flex-1">{t.title}</span>
              </span>
              <span className={cn('mono ml-14 block text-xs', t.overdue ? 'text-alert' : 'text-fog')}>
                {t.due_date ? formatDate(t.due_date) : ru.dash.noDate}
                {t.overdue && ` · ${ru.dash.overdueTag}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Tile>
  )
}

export function ContributionTile({
  rows,
  people,
}: {
  rows: DashboardData['contribution']
  people: Record<string, DashPerson>
}) {
  const max = Math.max(1, ...rows.map((r) => r.uploads + r.closed))
  return (
    <Tile title={ru.dash.contribution}>
      {rows.length === 0 ? (
        <p className="text-sm text-fog">{ru.dash.contributionEmpty}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => {
            const person = people[String(row.user_id)]
            if (!person) return null
            return (
              <li key={row.user_id}>
                <Link to={`/library?author=${row.user_id}`} className={cn(focus, 'flex min-h-[44px] items-center gap-3 rounded-lg px-1 transition-colors hover:bg-ink/60')}>
                  <Avatar user={person} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{person.name}</span>
                    <span className="mono block text-xs text-fog">{ru.dash.contributionLine(row.uploads, row.closed)}</span>
                    <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-line">
                      <span className="block h-full rounded-full" style={{ width: `${((row.uploads + row.closed) / max) * 100}%`, backgroundColor: person.color }} />
                    </span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Tile>
  )
}
