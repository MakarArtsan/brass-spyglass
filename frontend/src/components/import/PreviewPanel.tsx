import { Loader2, Rocket } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { clock } from '@/lib/format'
import type { ImportPreview, PreviewCard, PreviewScene } from '@/lib/scenarioImport'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

type Tab = 'characters' | 'locations' | 'assets'

/** Шкала хронометража: сколько получилось на фоне цели проекта. */
function TargetScale({ total, min, max, inTarget }: { total: number; min: number | null; max: number | null; inTarget: boolean | null }) {
  const top = Math.max(total, max ?? 0, 1) * 1.15
  const pct = (v: number) => `${Math.min(100, (v / top) * 100)}%`
  return (
    <div>
      <div className="relative h-3 overflow-hidden rounded-full bg-ink" role="img" aria-label={ru.importPage.scale(clock(total), min === null || max === null ? null : `${clock(min)}–${clock(max)}`)}>
        {min !== null && max !== null && (
          <div className="absolute inset-y-0 bg-status-done/30" style={{ left: pct(min), width: `calc(${pct(max)} - ${pct(min)})` }} />
        )}
        <div className={cn('absolute inset-y-0 left-0', inTarget === false ? 'bg-status-in_progress' : 'bg-brass')} style={{ width: pct(total) }} />
      </div>
      <p className={cn('mt-1.5 text-sm', inTarget === false && 'text-status-in_progress')}>
        {ru.importPage.scale(clock(total), min === null || max === null ? null : `${clock(min)}–${clock(max)}`)}
        {inTarget === false && ` — ${ru.importPage.outOfTarget}`}
      </p>
    </div>
  )
}

function Strip({ scenes }: { scenes: PreviewScene[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const scene = scenes.find((s) => s.number === open) ?? null
  return (
    <div>
      <div className="overflow-x-auto pb-2">
        <ol className="flex min-w-full gap-1" aria-label={ru.importPage.strip}>
          {scenes.map((s) => (
            <li key={s.number} style={{ flexGrow: Math.max(s.planned_sec, 1), flexBasis: 0 }} className="min-w-touch">
              <button
                type="button"
                aria-pressed={open === s.number}
                aria-label={ru.importPage.sceneLabel(s.number, s.title, clock(s.planned_sec))}
                onClick={() => setOpen(open === s.number ? null : s.number)}
                className={cn(
                  'flex min-h-[56px] w-full flex-col items-start justify-between rounded-lg border px-2 py-1 text-left transition-colors duration-fast',
                  open === s.number ? 'border-brass bg-brass/15' : 'border-line bg-chart hover:border-fog',
                )}
              >
                <span className="mono text-xs text-brass">{s.number}</span>
                <span className="mono text-[10px] text-fog">{clock(s.planned_sec)}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>
      {scene && (
        <div className="mt-2 space-y-2 rounded-xl border border-line p-3" aria-label={ru.importPage.sceneLabel(scene.number, scene.title, clock(scene.planned_sec))}>
          <div>
            <h4 className="text-lg">
              {scene.number}. {scene.title}
            </h4>
            <p className="text-xs text-fog">
              {[scene.location, ru.importPage.planned(clock(scene.planned_sec), clock(scene.shots_sec))].filter(Boolean).join(' · ')}
            </p>
            {scene.summary && <p className="mt-1 text-sm">{scene.summary}</p>}
          </div>
          <ol className="space-y-2">
            {scene.shots.map((shot) => (
              <li key={shot.position} className="rounded-lg bg-ink/60 p-2 text-sm">
                <div className="flex flex-wrap items-center gap-x-3 text-xs text-fog">
                  <span className="mono text-brass">
                    {String(scene.number).padStart(2, '0')}.{String(shot.position).padStart(2, '0')}
                  </span>
                  {shot.size && <span>{shot.size}</span>}
                  <span className="mono">{shot.duration_sec} с</span>
                </div>
                <p>{shot.description}</p>
                {shot.dialogue.map((line, i) => (
                  <p key={i} className="mt-1 border-l-2 border-brass/50 pl-2 text-xs italic">
                    {line.who && <span className="not-italic text-fog">{line.who}: </span>}
                    {line.text}
                  </p>
                ))}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

function Cards({ items, excluded, onToggle }: { items: PreviewCard[]; excluded: Set<string>; onToggle: (code: string) => void }) {
  if (items.length === 0) return <p className="text-sm text-fog">{ru.importPage.none}</p>
  return (
    <ul className="divide-y divide-line rounded-xl border border-line">
      {items.map((c) => (
        <li key={c.code} className={cn('flex items-start gap-3 px-3', excluded.has(c.code) && 'opacity-50')}>
          <label className="flex min-h-touch flex-1 cursor-pointer items-start gap-3 py-2.5">
            <input
              type="checkbox"
              checked={excluded.has(c.code)}
              onChange={() => onToggle(c.code)}
              aria-label={ru.importPage.skipCard(c.name)}
              className="mt-1 h-5 w-5 shrink-0 accent-brass"
            />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">
                {c.name} <span className="mono text-xs font-normal text-fog">{c.code}</span>
              </span>
              <span className="block text-xs text-fog">
                {[c.kind, ru.importPage.shotsCount(c.shots), c.states.length > 0 ? ru.importPage.statesCount(c.states.length) : null].filter(Boolean).join(' · ')}
              </span>
              {c.states.length > 0 && <span className="block text-xs text-fog">{c.states.join(', ')}</span>}
            </span>
          </label>
        </li>
      ))}
    </ul>
  )
}

interface Props {
  preview: ImportPreview
  canApply: boolean
  notEmptyReason: string | null
  excluded: Set<string>
  creating: boolean
  onToggle: (code: string) => void
  onCreate: () => void
}

/** Шаг 3: что получится. Ничего не записано, пока не нажали «Создать». */
export function PreviewPanel({ preview, canApply, notEmptyReason, excluded, creating, onToggle, onCreate }: Props) {
  const [tab, setTab] = useState<Tab>('characters')
  const lists: Record<Tab, PreviewCard[]> = { characters: preview.characters, locations: preview.locations, assets: preview.assets }

  return (
    <section aria-labelledby="import-step-3" className="space-y-5 rounded-2xl border border-line bg-chart/60 p-5">
      <div>
        <h2 id="import-step-3" className="text-2xl">
          {ru.importPage.step3}
        </h2>
        <p className="text-sm text-fog">{ru.importPage.previewLead}</p>
      </div>

      <div>
        <h3 className="text-3xl">{preview.title}</h3>
        {preview.title_en && preview.title_en !== preview.title && <p className="text-sm text-fog">{preview.title_en}</p>}
        {preview.logline && <p className="mt-1 text-sm">{preview.logline}</p>}
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7" aria-label={ru.importPage.counters}>
        {(['scenes', 'shots', 'characters', 'locations', 'assets', 'dialogue', 'setups'] as const).map((key) => (
          <div key={key} className="rounded-lg border border-line bg-ink/60 px-3 py-2">
            <dd className="mono text-2xl text-brass">{preview.counts[key]}</dd>
            <dt className="text-xs text-fog">{ru.importPage.counts[key]}</dt>
          </div>
        ))}
      </dl>

      <TargetScale total={preview.total_sec} min={preview.target_min_sec} max={preview.target_max_sec} inTarget={preview.in_target} />

      <div>
        <h3 className="mb-2 text-xl">{ru.importPage.strip}</h3>
        <p className="mb-2 text-xs text-fog">{ru.importPage.stripHint}</p>
        <Strip scenes={preview.scenes} />
      </div>

      <div>
        <div role="tablist" aria-label={ru.importPage.cards} className="mb-3 flex flex-wrap gap-1.5">
          {(['characters', 'locations', 'assets'] as const).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                'min-h-touch rounded-full border px-4 text-sm font-semibold transition-colors duration-fast',
                tab === key ? 'border-brass bg-brass/15 text-brass-light' : 'border-line text-fog hover:border-fog hover:text-paper',
              )}
            >
              {ru.importPage.tabs[key]} · {lists[key].length}
            </button>
          ))}
        </div>
        <p className="mb-2 text-xs text-fog">{ru.importPage.skipHint}</p>
        <div role="tabpanel">
          <Cards items={lists[tab]} excluded={excluded} onToggle={onToggle} />
        </div>
      </div>

      {preview.open_questions.length > 0 && (
        <div>
          <h3 className="text-xl">{ru.importPage.questions(preview.open_questions.length)}</h3>
          <p className="mb-2 text-xs text-fog">{ru.importPage.questionsHint}</p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {preview.open_questions.map((q) => (
              <li key={q.question}>
                {q.question}
                {q.related.length > 0 && <span className="text-fog"> ({q.related.join(', ')})</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {notEmptyReason && (
        <p role="alert" className="rounded-xl border border-alert/50 bg-alert/5 p-3 text-sm text-alert">
          {notEmptyReason}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="lg" disabled={!canApply || creating} onClick={onCreate}>
          {creating ? <Loader2 size={18} className="animate-spin" aria-hidden /> : <Rocket size={18} aria-hidden />}
          {creating ? ru.importPage.creating : ru.importPage.create}
        </Button>
        {excluded.size > 0 && <span className="text-sm text-fog">{ru.importPage.skipped(excluded.size)}</span>}
      </div>
    </section>
  )
}
