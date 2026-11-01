import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Comments } from '@/components/Comments'
import { DrumLevel } from '@/components/DrumLevel'
import { EditableSelect, EditableText } from '@/components/Editable'
import { History } from '@/components/History'
import { Lens } from '@/components/Lens'
import { FilesSection } from '@/components/media/FilesSection'
import { Field, Section } from '@/components/Section'
import { StatusPill } from '@/components/StatusPill'
import { usePerms } from '@/hooks/usePerms'
import { num, timecode } from '@/lib/format'
import { useScenes, useSetFinal, useShots, useUpdate } from '@/lib/queries'
import { toast } from '@/lib/toast'
import type { Scene, Shot, StatusKey } from '@/lib/types'
import { ru } from '@/ru'
import NotFound from '@/pages/NotFound'

function ShotCardLink({ shot }: { shot: Shot }) {
  return (
    <Link
      to={`/shots?shot=${shot.id}`}
      className="group flex min-h-touch items-center gap-3 rounded-xl border border-line bg-chart p-2 outline-none hover:border-brass focus-visible:ring-2 focus-visible:ring-brass"
      aria-label={`${ru.shots.card}: ${shot.code}`}
    >
      <Lens decorative size={44} src={shot.preview?.url} alt={shot.code}>
        <span className="block h-full w-full bg-ink" />
      </Lens>
      <span className="min-w-0 flex-1">
        <span className="mono text-sm font-semibold text-brass">{shot.code}</span>
        <span className="mono ml-2 text-xs text-fog">
          {num(shot.duration_sec)} {ru.common.sec}
        </span>
        <span className="line-clamp-1 block text-xs text-fog">{shot.description}</span>
      </span>
      <StatusPill status={shot.status} />
    </Link>
  )
}

/** Страница сцены: смысл, барабан, таймкоды, лента шотов; если у шотов указана сторона — Север и Юг рядом. */
export default function SceneDetail() {
  const { id } = useParams()
  const perms = usePerms()
  const { data: scenes } = useScenes()
  const { data: shots } = useShots()
  const update = useUpdate<Scene>('scenes')
  const scene = scenes?.find((s) => String(s.id) === id)
  const setFinal = useSetFinal('scene', scene?.id ?? 0)

  if (!scenes) return <p className="text-fog">{ru.common.loading}</p>
  if (!scene) return <NotFound />
  const editable = perms.canEdit(scene)
  const save = (patch: Record<string, unknown>) => update.mutate({ id: scene.id, patch })
  const own = (shots ?? []).filter((s) => s.scene_id === scene.id)
  const north = own.filter((s) => s.side === 'north')
  const south = own.filter((s) => s.side === 'south')
  const paired = north.length + south.length > 0

  return (
    <article className="space-y-6">
      <Link to="/scenes" className="inline-flex min-h-touch items-center gap-1.5 text-sm text-fog hover:text-paper">
        <ArrowLeft size={16} />
        {ru.scenes.title}
      </Link>

      <header className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="mono text-3xl font-semibold text-brass">{String(scene.number).padStart(2, '0')}</span>
          <h1 className="text-4xl">{scene.title}</h1>
          <StatusPill status={scene.status} onChange={perms.canStatus ? (status: StatusKey) => update.mutate({ id: scene.id, patch: { status } }) : undefined} />
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <span className="mono">{scene.status === 'cut' ? ru.scenes.cutOut : `${timecode(scene.start_sec)}–${timecode(scene.end_sec)}`}</span>
          <span className="mono text-fog">
            {ru.scenes.planned}: {num(scene.planned_sec)} {ru.common.sec}
          </span>
          <span className="flex items-center gap-2 text-fog">
            {ru.scenes.drum} <DrumLevel level={scene.drum_level} />
          </span>
          <span className={Math.abs(scene.delta_sec) > 0.01 ? 'text-status-in_progress' : 'text-status-done'}>
            {Math.abs(scene.delta_sec) > 0.01 ? ru.scenes.delta(scene.delta_sec) : ru.scenes.deltaOk}
          </span>
        </div>
      </header>

      <div className="grid gap-x-6 gap-y-3 md:grid-cols-2">
        <Field label={ru.scenes.sceneTitle}>
          <EditableText value={scene.title} readOnly={!editable} ariaLabel={ru.scenes.sceneTitle} onSave={(v) => v && save({ title: v })} />
        </Field>
        <Field label={ru.scenes.planned}>
          <EditableText value={scene.planned_sec} numeric mono readOnly={!editable} ariaLabel={ru.scenes.planned} onSave={(v) => save({ planned_sec: v == null ? 0 : Number(v) })} />
        </Field>
        <Field label={ru.scenes.location}>
          <EditableText value={scene.location} readOnly={!editable} ariaLabel={ru.scenes.location} onSave={(v) => save({ location: v })} />
        </Field>
        <Field label={ru.scenes.timeOfDay}>
          <EditableText value={scene.time_of_day} readOnly={!editable} ariaLabel={ru.scenes.timeOfDay} onSave={(v) => save({ time_of_day: v })} />
        </Field>
        <Field label={ru.scenes.drum}>
          <EditableSelect
            value={scene.drum_level == null ? null : String(scene.drum_level)}
            readOnly={!editable}
            ariaLabel={ru.scenes.drum}
            onChange={(v) => save({ drum_level: v == null ? null : Number(v) })}
            options={[0, 1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))}
          />
        </Field>
        <Field label={ru.scenes.characters}>
          <EditableText value={scene.characters} readOnly={!editable} ariaLabel={ru.scenes.characters} onSave={(v) => save({ characters: v })} />
        </Field>
        <Field label={ru.scenes.keyAssets} className="md:col-span-2">
          <EditableText value={scene.key_assets} multiline readOnly={!editable} ariaLabel={ru.scenes.keyAssets} onSave={(v) => save({ key_assets: v })} />
        </Field>
        <Field label={ru.scenes.meaning} className="md:col-span-2">
          <EditableText value={scene.meaning} multiline readOnly={!editable} ariaLabel={ru.scenes.meaning} onSave={(v) => save({ meaning: v })} />
        </Field>
        <Field label={ru.scenes.lines} className="md:col-span-2">
          <EditableText value={scene.lines_en} multiline readOnly={!editable} ariaLabel={ru.scenes.lines} onSave={(v) => save({ lines_en: v })} />
        </Field>
        <Field label={ru.scenes.cutNotes} className="md:col-span-2">
          <EditableText value={scene.cut_notes} multiline readOnly={!editable} ariaLabel={ru.scenes.cutNotes} onSave={(v) => save({ cut_notes: v })} />
        </Field>
      </div>

      <FilesSection
        title={ru.scenes.finalFile}
        entityType="scene"
        entityId={scene.id}
        purposes={['final']}
        uploadPurpose="final"
        finalId={scene.final?.id ?? null}
        onSetFinal={editable ? (fileId) => setFinal.mutate(fileId, { onSuccess: () => toast(fileId == null ? ru.files.finalCleared : ru.files.finalSet) }) : undefined}
      />
      <p className="-mt-3 text-xs text-fog">{scene.final ? `${scene.final.original_name ?? ''} · v${scene.final.version_no}` : `${ru.scenes.finalNone}. ${ru.scenes.finalFileHint}`}</p>

      <Section title={ru.scenes.ribbon}>
        {own.length === 0 ? (
          <p className="text-sm text-fog">{ru.scenes.noShots}</p>
        ) : paired ? (
          <div className="grid gap-4 md:grid-cols-2">
            {[
              { title: ru.scenes.north, items: north, color: 'text-north' },
              { title: ru.scenes.south, items: south, color: 'text-south' },
            ].map((col) => (
              <div key={col.title} className="space-y-2">
                <h4 className={`font-display text-xl ${col.color}`}>{col.title}</h4>
                {col.items.map((s) => (
                  <ShotCardLink key={s.id} shot={s} />
                ))}
              </div>
            ))}
            {own.some((s) => !s.side) && (
              <div className="space-y-2 md:col-span-2">
                {own
                  .filter((s) => !s.side)
                  .map((s) => (
                    <ShotCardLink key={s.id} shot={s} />
                  ))}
              </div>
            )}
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {own.map((s) => (
              <ShotCardLink key={s.id} shot={s} />
            ))}
          </div>
        )}
      </Section>

      <FilesSection title={ru.shots.referencesTitle} entityType="scene" entityId={scene.id} purposes={['reference', 'blockout', 'other', 'take']} uploadPurpose="reference" />
      <Comments entityType="scene" entityId={scene.id} />
      <History entityType="scene" entityId={scene.id} />
    </article>
  )
}
