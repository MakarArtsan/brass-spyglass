import { Countdown } from '@/components/Countdown'
import { StatusChip } from '@/components/StatusChip'
import { STATUS_ORDER } from '@/brand'
import { useMe, useProject } from '@/hooks/useAuth'
import { ru } from '@/ru'

const dubaiDate = new Intl.DateTimeFormat('ru-RU', { timeZone: 'Asia/Dubai', day: 'numeric', month: 'long', year: 'numeric' })

const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`

function Fact({ label, value, sub, wide }: { label: string; value: string; sub?: string; wide?: boolean }) {
  return (
    <div className={`panel p-4 ${wide ? 'col-span-2 xl:col-span-1' : ''}`}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-fog">{label}</div>
      <div className="mono mt-2 text-base font-semibold sm:text-xl">{value}</div>
      {sub && <div className="mt-1 text-xs text-fog">{sub}</div>}
    </div>
  )
}

/** Дашборд-витрина проекта. Виджеты со статистикой появятся на этапе 2. */
export default function Dashboard() {
  const { data: me } = useMe()
  const { data: project } = useProject()
  if (!me) return null
  return (
    <section className="space-y-6">
      <div>
        <p className="mono text-xs uppercase tracking-[0.2em] text-brass">{ru.dashboard.welcome}</p>
        <h1 className="mt-1 text-4xl">{ru.dashboard.hello(me.user.name)}</h1>
        <p className="mt-2 max-w-2xl text-fog">{ru.dashboard.stageNote}</p>
      </div>

      {!project && <div aria-hidden className="min-h-[640px]" />}
      {project && (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Fact label={ru.dashboard.contest} value={project.contest} wide />
            <Fact label={ru.dashboard.format} value={`${project.fps} fps`} sub={`${project.width} × ${project.height}`} />
            <Fact
              label={ru.dashboard.runtime}
              value={`${mmss(project.target_min_sec)}–${mmss(project.target_max_sec)}`}
              sub={ru.dashboard.targetRuntime(mmss(project.target_min_sec), mmss(project.target_max_sec))}
            />
            <Fact label={ru.dashboard.project} value={project.title_en} sub={project.title} wide />
          </div>

          <div className="panel grid gap-6 p-5 md:grid-cols-2">
            <div className="space-y-2">
              <Countdown target={project.deadline_internal} label={ru.dashboard.internalDeadline} />
              <p className="text-sm text-fog">{dubaiDate.format(new Date(project.deadline_internal))}</p>
            </div>
            <div className="space-y-2">
              <Countdown target={project.deadline_official} label={ru.dashboard.officialDeadline} />
              <p className="text-sm text-fog">
                {dubaiDate.format(new Date(project.deadline_official))} · {ru.dashboard.dubai}
              </p>
            </div>
          </div>
        </>
      )}

      <div className="flex flex-wrap gap-2" aria-label="Статусы">
        {STATUS_ORDER.map((s) => (
          <StatusChip key={s} status={s} />
        ))}
      </div>
    </section>
  )
}
