import { Copy, Download, Plus, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Comments } from '@/components/Comments'
import { EditableSelect, EditableText } from '@/components/Editable'
import { History } from '@/components/History'
import { FilesSection } from '@/components/media/FilesSection'
import { Field, Section } from '@/components/Section'
import { StatusPill } from '@/components/StatusPill'
import { usePerms } from '@/hooks/usePerms'
import { toast } from '@/lib/toast'
import { useAssets, useEntityFiles, useFileMutations, useMeta, useShot, useShotAsset, useUpdate } from '@/lib/queries'
import type { Shot, StatusKey } from '@/lib/types'
import { ru } from '@/ru'

const options = (values: string[] | undefined, labels: Record<string, string>) =>
  (values ?? []).map((v) => ({ value: v, label: labels[v] ?? v }))

export function ShotCardTitle({ shotId }: { shotId: number }) {
  const { data: shot } = useShot(shotId)
  const perms = usePerms()
  const update = useUpdate<Shot>('shots')
  if (!shot) return <span className="text-fog">{ru.common.loading}</span>
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h2 className="mono text-2xl font-semibold">{shot.code}</h2>
      <StatusPill
        status={shot.status}
        onChange={perms.canStatus ? (status: StatusKey) => update.mutate({ id: shot.id, patch: { status } }) : undefined}
      />
      {shot.scene && (
        <span className="w-full truncate text-xs text-fog">
          {ru.scenes.scene(shot.scene.number)} · {shot.scene.title}
        </span>
      )}
    </div>
  )
}

/** Карточка шота: параметры, дубли и промпт, референсы, ассеты с состояниями, звук, комментарии, история. */
export function ShotCard({ shotId }: { shotId: number }) {
  const { data: shot } = useShot(shotId)
  const { data: meta } = useMeta()
  const { data: assets } = useAssets()
  const { data: attached } = useEntityFiles('shot', shotId)
  const perms = usePerms()
  const update = useUpdate<Shot>('shots')
  const link = useShotAsset(shotId)
  const fileMutations = useFileMutations('shot', shotId)

  if (!shot) return <p className="p-4 text-sm text-fog">{ru.common.loading}</p>
  const editable = perms.canEdit(shot)
  const save = (patch: Record<string, unknown>) => update.mutate({ id: shot.id, patch })

  const takes = (attached ?? []).filter((a) => a.purpose === 'take')
  const latest = takes.at(-1)?.file
  const canEditFile = latest ? perms.canEdit({ uploaded_by: latest.uploaded_by }) : false
  const saveFile = (patch: Record<string, unknown>) => latest && fileMutations.update.mutate({ fileId: latest.id, patch })

  const present = new Set(shot.assets.map((a) => a.asset_id))
  const available = (assets ?? []).filter((a) => !present.has(a.id))
  const assetById = new Map((assets ?? []).map((a) => [a.id, a]))

  return (
    <div className="space-y-6 p-4">
      <Field label={ru.shots.description}>
        <EditableText value={shot.description} onSave={(v) => save({ description: v })} readOnly={!editable} multiline ariaLabel={ru.shots.description} />
      </Field>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2">
        <Field label={ru.shots.size}>
          <EditableSelect value={shot.size} readOnly={!editable} ariaLabel={ru.shots.size} onChange={(v) => save({ size: v })} options={options(meta?.size, ru.size)} />
        </Field>
        <Field label={ru.shots.duration}>
          <EditableText value={shot.duration_sec} numeric mono readOnly={!editable} ariaLabel={ru.shots.duration} onSave={(v) => save({ duration_sec: v == null ? 0 : Number(v) })} />
        </Field>
        <Field label={ru.shots.tool}>
          <EditableSelect value={shot.tool} readOnly={!editable} ariaLabel={ru.shots.tool} onChange={(v) => save({ tool: v })} options={options(meta?.tool, ru.tool)} />
        </Field>
        <Field label={ru.shots.stage}>
          <EditableSelect value={shot.stage} readOnly={!editable} ariaLabel={ru.shots.stage} onChange={(v) => save({ stage: v })} options={options(meta?.stage, ru.stage)} />
        </Field>
        <Field label={ru.shots.camera} className="col-span-2">
          <EditableText value={shot.camera} readOnly={!editable} ariaLabel={ru.shots.camera} onSave={(v) => save({ camera: v })} />
        </Field>
        <Field label={ru.shots.soundNote} className="col-span-2">
          <EditableText value={shot.sound_note} readOnly={!editable} ariaLabel={ru.shots.soundNote} onSave={(v) => save({ sound_note: v })} />
        </Field>
        <Field label={ru.shots.priority}>
          <EditableSelect value={shot.priority} readOnly={!editable} ariaLabel={ru.shots.priority} onChange={(v) => save({ priority: v })} options={options(meta?.priority, ru.priority)} />
        </Field>
      </div>

      <FilesSection title={ru.shots.takesTitle} entityType="shot" entityId={shot.id} purposes={['take', 'final']} uploadPurpose="take" />

      {latest && (
        <Section
          title={ru.shots.prompt}
          actions={
            latest.ai_prompt && (
              <button
                type="button"
                onClick={() => navigator.clipboard.writeText(latest.ai_prompt ?? '').then(() => toast(ru.common.copied))}
                className="flex min-h-touch items-center gap-1.5 rounded-lg px-2 text-xs text-brass hover:bg-ink"
              >
                <Copy size={14} />
                {ru.shots.copyPrompt}
              </button>
            )
          }
        >
          <div className="rounded-xl border border-line p-2">
            <EditableText value={latest.ai_prompt} multiline readOnly={!canEditFile} placeholder={ru.shots.noPrompt} ariaLabel={ru.shots.prompt} onSave={(v) => saveFile({ ai_prompt: v })} />
            <div className="grid grid-cols-2 gap-x-3">
              <Field label={ru.shots.aiTool}>
                <EditableText value={latest.ai_tool} readOnly={!canEditFile} ariaLabel={ru.shots.aiTool} onSave={(v) => saveFile({ ai_tool: v })} />
              </Field>
              <Field label={ru.shots.aiSeed}>
                <EditableText value={latest.ai_seed} mono readOnly={!canEditFile} ariaLabel={ru.shots.aiSeed} onSave={(v) => saveFile({ ai_seed: v })} />
              </Field>
            </div>
          </div>
        </Section>
      )}

      <FilesSection title={ru.shots.referencesTitle} entityType="shot" entityId={shot.id} purposes={['reference', 'blockout', 'sound', 'music', 'subtitles', 'other']} uploadPurpose="reference" />

      <Section title={ru.shots.assetsTitle}>
        <ul className="space-y-1">
          {shot.assets.map((ref) => {
            const states = assetById.get(ref.asset_id)?.states ?? []
            return (
              <li key={ref.asset_id} className="flex items-center gap-2 rounded-lg border border-line px-2">
                <Link to={`/assets?asset=${ref.asset_id}`} className="flex min-h-touch min-w-0 flex-1 items-center gap-2 text-sm hover:text-brass-light">
                  <span className="mono shrink-0 text-xs text-brass">{ref.code}</span>
                  <span className="truncate">{ref.name}</span>
                </Link>
                {states.length > 0 && (
                  <EditableSelect
                    className="!w-auto max-w-[150px]"
                    value={ref.state_id == null ? null : String(ref.state_id)}
                    readOnly={!editable}
                    ariaLabel={`${ru.shots.state}: ${ref.code}`}
                    onChange={(v) => link.set.mutate({ assetId: ref.asset_id, stateId: v == null ? null : Number(v) })}
                    options={states.map((s) => ({ value: String(s.id), label: s.name }))}
                  />
                )}
                {editable && (
                  <button
                    type="button"
                    aria-label={`${ru.shots.removeAsset}: ${ref.code}`}
                    onClick={() => link.remove.mutate(ref.asset_id)}
                    className="flex min-h-touch min-w-touch items-center justify-center rounded text-fog hover:text-alert"
                  >
                    <X size={16} />
                  </button>
                )}
              </li>
            )
          })}
        </ul>
        {editable && available.length > 0 && (
          <label className="flex items-center gap-2 text-sm text-brass">
            <Plus size={16} aria-hidden />
            <select
              aria-label={ru.shots.addAsset}
              value=""
              onChange={(e) => e.target.value && link.set.mutate({ assetId: Number(e.target.value), stateId: null })}
              className="min-h-touch flex-1 cursor-pointer rounded-lg bg-transparent px-1 text-sm outline-none hover:bg-ink"
            >
              <option value="">{ru.shots.addAsset}</option>
              {available.map((a) => (
                <option key={a.id} value={a.id} className="bg-chart text-paper">
                  {a.code} · {a.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </Section>

      {shot.sound.length > 0 && (
        <Section title={ru.shots.soundTitle}>
          <ul className="space-y-1.5">
            {shot.sound.map((c) => (
              <li key={c.id} className="rounded-lg border border-line p-2 text-sm">
                <div className="flex gap-2 text-xs text-fog">
                  <span className="mono text-brass">{c.code}</span>
                  <span>{ru.soundType[c.type as keyof typeof ru.soundType]}</span>
                  {c.who && <span className="truncate">· {c.who}</span>}
                </div>
                {c.text_en && <p className="mt-1">{c.text_en}</p>}
                {c.text_ru && <p className="text-xs text-fog">{c.text_ru}</p>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {shot.setups.length > 0 && (
        <Section title={ru.shots.setupsTitle}>
          <ul className="space-y-1">
            {shot.setups.map((s) => (
              <li key={`${s.id}-${s.role}`} className="flex gap-2 rounded-lg border border-line px-2 py-2 text-sm">
                <span className="mono shrink-0 text-xs text-brass">№{s.number}</span>
                <span className="min-w-0 flex-1 truncate">{s.motif}</span>
                <span className="shrink-0 text-xs text-fog">{ru.shots.setupRole[s.role]}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {shot.files_count > 0 && (
        <a
          href={`/api/entities/shot/${shot.id}/zip`}
          className="inline-flex min-h-touch items-center gap-2 text-sm text-brass hover:text-brass-light"
        >
          <Download size={16} />
          {ru.shots.downloadAll}
        </a>
      )}

      <Comments entityType="shot" entityId={shot.id} />
      <History entityType="shot" entityId={shot.id} />
    </div>
  )
}
