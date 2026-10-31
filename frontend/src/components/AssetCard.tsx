import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Comments } from '@/components/Comments'
import { EditableSelect, EditableText } from '@/components/Editable'
import { History } from '@/components/History'
import { FilesSection } from '@/components/media/FilesSection'
import { Field, Section } from '@/components/Section'
import { StatusPill } from '@/components/StatusPill'
import { Button } from '@/components/ui/button'
import { usePerms } from '@/hooks/usePerms'
import { useAsset, useAssetStates, useMeta, useUpdate } from '@/lib/queries'
import type { Asset, StatusKey } from '@/lib/types'
import { ru } from '@/ru'

export function AssetCardTitle({ assetId }: { assetId: number }) {
  const { data: asset } = useAsset(assetId)
  const perms = usePerms()
  const update = useUpdate<Asset>('assets')
  if (!asset) return <span className="text-fog">{ru.common.loading}</span>
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h2 className="mono text-2xl font-semibold">{asset.code}</h2>
      <StatusPill
        status={asset.status}
        onChange={perms.canStatus ? (status: StatusKey) => update.mutate({ id: asset.id, patch: { status } }) : undefined}
      />
      <span className="w-full truncate text-xs text-fog">{asset.name}</span>
    </div>
  )
}

/** Карточка ассета: состояния (у овцы четыре) со своими референсами и шоты, где ассет в кадре. */
export function AssetCard({ assetId }: { assetId: number }) {
  const { data: asset } = useAsset(assetId)
  const { data: meta } = useMeta()
  const perms = usePerms()
  const update = useUpdate<Asset>('assets')
  const states = useAssetStates(assetId)
  const [newState, setNewState] = useState('')

  if (!asset) return <p className="p-4 text-sm text-fog">{ru.common.loading}</p>
  const editable = perms.canEdit(asset)
  const save = (patch: Record<string, unknown>) => update.mutate({ id: asset.id, patch })

  return (
    <div className="space-y-6 p-4">
      <div className="grid grid-cols-2 gap-x-3 gap-y-2">
        <Field label={ru.assets.name} className="col-span-2">
          <EditableText value={asset.name} readOnly={!editable} ariaLabel={ru.assets.name} onSave={(v) => v && save({ name: v })} />
        </Field>
        <Field label={ru.assets.type}>
          <EditableSelect
            value={asset.type}
            allowEmpty={false}
            readOnly={!editable}
            ariaLabel={ru.assets.type}
            onChange={(v) => v && save({ type: v })}
            options={(meta?.asset_type ?? []).map((t) => ({ value: t, label: ru.assetType[t as keyof typeof ru.assetType] ?? t }))}
          />
        </Field>
        <Field label={ru.shots.priority}>
          <EditableSelect
            value={asset.priority}
            readOnly={!editable}
            ariaLabel={ru.shots.priority}
            onChange={(v) => save({ priority: v })}
            options={(meta?.priority ?? []).map((p) => ({ value: p, label: ru.priority[p as keyof typeof ru.priority] ?? p }))}
          />
        </Field>
        <Field label={ru.assets.description} className="col-span-2">
          <EditableText value={asset.description} multiline readOnly={!editable} ariaLabel={ru.assets.description} onSave={(v) => save({ description: v })} />
        </Field>
      </div>

      <Section title={ru.assets.states}>
        {asset.states.length === 0 && <p className="text-sm text-fog">{ru.assets.noStates}</p>}
        <div className="space-y-3">
          {asset.states.map((state) => (
            <div key={state.id} className="space-y-2 rounded-xl border border-line p-2">
              <div className="flex items-center gap-2">
                <EditableText
                  value={state.name}
                  readOnly={!editable}
                  ariaLabel={ru.assets.stateName}
                  className="font-semibold"
                  onSave={(v) => v && states.rename.mutate({ id: state.id, name: v })}
                />
                {editable && (
                  <button
                    type="button"
                    aria-label={`${ru.common.delete}: ${state.name}`}
                    onClick={() => window.confirm(`${ru.common.delete}: ${state.name}?`) && states.remove.mutate(state.id)}
                    className="flex min-h-touch min-w-touch items-center justify-center rounded text-fog hover:text-alert"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
              <FilesSection title={ru.assets.stateReferences} entityType="asset_state" entityId={state.id} purposes={['reference', 'other']} uploadPurpose="reference" />
            </div>
          ))}
        </div>
        {editable && (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              const name = newState.trim()
              if (name) states.create.mutate(name, { onSuccess: () => setNewState('') })
            }}
          >
            <input
              value={newState}
              onChange={(e) => setNewState(e.target.value)}
              maxLength={300}
              placeholder={ru.assets.stateName}
              aria-label={ru.assets.stateName}
              className="min-h-touch flex-1 rounded-lg border border-line bg-ink px-3 text-sm outline-none focus:border-brass"
            />
            <Button type="submit" variant="outline" disabled={!newState.trim()}>
              <Plus size={16} />
              {ru.assets.addState}
            </Button>
          </form>
        )}
      </Section>

      <FilesSection title={ru.assets.references} entityType="asset" entityId={asset.id} purposes={['reference', 'other']} uploadPurpose="reference" />

      <Section title={ru.assets.inShots}>
        {asset.shots.length === 0 ? (
          <p className="text-sm text-status-rework">{ru.assets.noShots}</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {asset.shots.map((s) => (
              <Link
                key={s.id}
                to={`/shots?shot=${s.id}`}
                className="mono flex min-h-touch items-center rounded-lg border border-line px-3 text-xs hover:border-brass hover:text-brass-light"
              >
                {s.code}
              </Link>
            ))}
          </div>
        )}
      </Section>

      <Comments entityType="asset" entityId={asset.id} />
      <History entityType="asset" entityId={asset.id} />
    </div>
  )
}
