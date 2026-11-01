import { Film } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { useAnimatic, type AnimaticShot, type SoundBlock } from '@/lib/animatic'
import { clock } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const FilmPlayer = lazy(() => import('@/components/animatic/FilmPlayer'))

const LABEL_W = 112
const H = { ruler: 24, scene: 44, shot: 56, lane: 28 } as const
const LANES = [1, 2, 3] as const
const LANE_COLOR: Record<number, string> = { 1: 'bg-brass/70', 2: 'bg-south/60', 3: 'bg-north/60' }

function Ruler({ total, pps }: { total: number; pps: number }) {
  const step = pps >= 20 ? 5 : pps >= 10 ? 10 : 30
  const marks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step)
  return (
    <div className="relative border-b border-line" style={{ height: H.ruler }} aria-hidden>
      {marks.map((t) => (
        <span key={t} className="mono absolute top-1 -translate-x-1/2 text-[10px] text-fog" style={{ left: t * pps }}>
          {clock(t)}
        </span>
      ))}
    </div>
  )
}

function ShotBlock({ shot, pps }: { shot: AnimaticShot; pps: number }) {
  const width = Math.max(2, (shot.end_sec - shot.start_sec) * pps - 2)
  const hasFile = shot.final !== null
  return (
    <Link
      to={`/shots?shot=${shot.id}`}
      aria-label={`${ru.animatic.openShot(shot.code)}: ${hasFile ? ru.animatic.hasFile : ru.animatic.noFile}`}
      title={`${shot.code} · ${clock(shot.duration_sec)} · ${shot.description ?? ''}`}
      className={cn(
        'absolute top-0 flex flex-col justify-between overflow-hidden rounded-md border px-1 py-0.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-brass',
        hasFile ? 'border-line bg-chart' : 'border-dashed border-line bg-ink/60',
      )}
      style={{
        left: shot.start_sec * pps,
        width,
        height: H.shot,
        borderTop: `3px solid rgb(var(--status-${shot.status}))`,
      }}
    >
      <span className="mono truncate text-[10px] leading-tight">{shot.code}</span>
      {hasFile && <Film size={12} className="text-brass" aria-hidden />}
    </Link>
  )
}

function CueBlock({ cue, pps }: { cue: SoundBlock; pps: number }) {
  const label = `${cue.code}${cue.who ? ` · ${cue.who}` : ''}${cue.text_en ? `: ${cue.text_en}` : ''} (${cue.has_file ? ru.animatic.cueWithFile : ru.animatic.cueNoFile})`
  return (
    <div
      role="img"
      aria-label={label}
      title={label}
      className={cn('absolute top-0.5 overflow-hidden rounded px-1 text-[10px] leading-6 text-ink', LANE_COLOR[cue.lane], !cue.has_file && 'opacity-60')}
      style={{ left: cue.start_sec * pps, width: Math.max(4, (cue.end_sec - cue.start_sec) * pps - 1), height: H.lane - 4 }}
    >
      <span className="mono truncate">{cue.code}</span>
    </div>
  )
}

/** Аниматик: таймлайн фильма и «Смотреть фильм» — готовые файлы подряд, а где их нет — карточка с описанием. */
export default function Animatic() {
  const { data } = useAnimatic()
  const [pps, setPps] = useState(14)
  const [watching, setWatching] = useState(false)
  const [playhead, setPlayhead] = useState<number | null>(null)
  const scroller = useRef<HTMLDivElement>(null)

  // Бегунок не должен уходить за край экрана, пока идёт просмотр.
  useEffect(() => {
    const box = scroller.current
    if (playhead == null || !box) return
    const x = playhead * pps
    if (x < box.scrollLeft || x > box.scrollLeft + box.clientWidth - 40) box.scrollTo({ left: Math.max(0, x - 80) })
  }, [playhead, pps])

  if (!data) return <p className="text-fog">{ru.common.loading}</p>
  const width = Math.ceil(data.total_sec * pps) + 24
  const shotsTotal = data.playlist.length
  const rows: { label: string; height: number }[] = [
    { label: '', height: H.ruler },
    { label: ru.animatic.scenes, height: H.scene },
    { label: ru.animatic.shots, height: H.shot },
    ...LANES.map((lane) => ({ label: ru.animatic.laneNames[lane], height: H.lane })),
  ]

  return (
    <section>
      <PageHeader
        title={ru.animatic.title}
        lead={ru.animatic.lead}
        actions={
          <Button onClick={() => setWatching(true)} disabled={data.playlist.length === 0}>
            <Film size={16} aria-hidden />
            {ru.animatic.watch}
          </Button>
        }
      />
      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-fog">
        <span>{ru.animatic.total(clock(data.total_sec))}</span>
        <span>{ru.animatic.ready(data.ready_count, shotsTotal)}</span>
        <label className="ml-auto flex min-h-touch items-center gap-2">
          {ru.animatic.zoom}
          <input type="range" min={6} max={40} value={pps} onChange={(e) => setPps(Number(e.target.value))} className="w-32 accent-brass" />
        </label>
      </div>

      {data.scenes.length === 0 ? (
        <p className="py-10 text-center text-fog">{ru.animatic.empty}</p>
      ) : (
        <div className="flex rounded-xl border border-line bg-chart/40">
          <div className="shrink-0 border-r border-line" style={{ width: LABEL_W }}>
            {rows.map((row, i) => (
              <div key={i} className="flex items-center px-2 text-[11px] uppercase tracking-wider text-fog" style={{ height: row.height }}>
                {row.label}
              </div>
            ))}
          </div>
          <div ref={scroller} className="min-w-0 flex-1 overflow-x-auto">
            <div className="relative" style={{ width }}>
              <Ruler total={data.total_sec} pps={pps} />
              <div className="relative" style={{ height: H.scene }}>
                {data.scenes.map((s) => (
                  <Link
                    key={s.id}
                    to={`/scenes/${s.id}`}
                    className="absolute top-0 flex items-center gap-1 overflow-hidden rounded-md border border-line bg-ink/60 px-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-brass"
                    style={{ left: s.start_sec * pps, width: Math.max(2, (s.end_sec - s.start_sec) * pps - 2), height: H.scene - 2 }}
                    title={`${ru.scenes.scene(s.number)} · ${s.title}`}
                  >
                    <span className="mono text-brass">{s.number}</span>
                    <span className="truncate">{s.title}</span>
                  </Link>
                ))}
              </div>
              <div className="relative" style={{ height: H.shot }}>
                {data.scenes.flatMap((s) => s.shots).map((shot) => (
                  <ShotBlock key={shot.id} shot={shot} pps={pps} />
                ))}
              </div>
              {LANES.map((lane) => (
                <div key={lane} className="relative border-t border-line/60" style={{ height: H.lane }}>
                  {data.sound.filter((c) => c.lane === lane).map((cue) => (
                    <CueBlock key={cue.id} cue={cue} pps={pps} />
                  ))}
                </div>
              ))}
              {playhead != null && <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-alert" style={{ left: playhead * pps }} aria-hidden />}
            </div>
          </div>
        </div>
      )}

      {watching && (
        <Suspense fallback={null}>
          <FilmPlayer playlist={data.playlist} onClose={() => setWatching(false)} onPlayhead={setPlayhead} />
        </Suspense>
      )}
    </section>
  )
}
