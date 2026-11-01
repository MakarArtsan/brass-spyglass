import { Download, Plus } from 'lucide-react'
import { useState } from 'react'
import { FilterChips } from '@/components/Chips'
import { EditableSelect, EditableText } from '@/components/Editable'
import { PageHeader } from '@/components/PageHeader'
import { StatusPill } from '@/components/StatusPill'
import { Button } from '@/components/ui/button'
import { useMe } from '@/hooks/useAuth'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { usePerms } from '@/hooks/usePerms'
import { useCreate, useMeta, useShots, useSounds, useUpdate } from '@/lib/queries'
import type { SoundCue, StatusKey } from '@/lib/types'
import { ru } from '@/ru'

const nextCode = (cues: SoundCue[] | undefined) => {
  const n = Math.max(0, ...(cues ?? []).map((c) => Number(c.code.replace(/\D/g, '')) || 0)) + 1
  return `SND-${String(n).padStart(2, '0')}`
}

function NewCue({ cues, onDone }: { cues: SoundCue[] | undefined; onDone: () => void }) {
  const { data: meta } = useMeta()
  const create = useCreate<SoundCue>('sound')
  const [code, setCode] = useState(nextCode(cues))
  const [type, setType] = useState('sfx')
  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-chart p-3"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate({ code: code.trim(), type }, { onSuccess: onDone })
      }}
    >
      <label className="text-xs text-fog">
        {ru.sound.code}
        <input value={code} onChange={(e) => setCode(e.target.value)} required maxLength={16} className="mono mt-1 block min-h-touch w-32 rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <label className="text-xs text-fog">
        {ru.sound.type}
        <select value={type} onChange={(e) => setType(e.target.value)} className="mt-1 block min-h-touch rounded-lg border border-line bg-ink px-2 text-sm text-paper">
          {meta?.sound_type.map((t) => (
            <option key={t} value={t}>
              {ru.soundType[t as keyof typeof ru.soundType]}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={!code.trim() || create.isPending}>
        {ru.common.create}
      </Button>
      <Button type="button" variant="ghost" onClick={onDone}>
        {ru.common.cancel}
      </Button>
    </form>
  )
}

export default function Sound() {
  const desktop = useIsDesktop()
  const perms = usePerms()
  const { data: cues } = useSounds()
  const { data: meta } = useMeta()
  const { data: shots } = useShots()
  const update = useUpdate<SoundCue>('sound')
  const [types, setTypes] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const canExport = useMe().data?.abilities.export ?? false

  const visible = (cues ?? []).filter((c) => types.length === 0 || types.includes(c.type))
  const typeOptions = (meta?.sound_type ?? []).map((t) => ({ value: t, label: ru.soundType[t as keyof typeof ru.soundType] }))

  const bind = (c: SoundCue) => {
    const editable = perms.canEdit(c)
    const save = (patch: Record<string, unknown>) => update.mutate({ id: c.id, patch })
    return { editable, save }
  }
  const saveShot = (c: SoundCue, code: string | null) => {
    const shot = code ? shots?.find((s) => s.code === code.trim()) : undefined
    update.mutate({ id: c.id, patch: { shot_id: shot?.id ?? null, scene_id: shot?.scene_id ?? c.scene_id } })
  }
  const status = (c: SoundCue) => (
    <StatusPill status={c.status} onChange={perms.canStatus ? (next: StatusKey) => update.mutate({ id: c.id, patch: { status: next } }) : undefined} />
  )

  return (
    <div>
      <PageHeader
        title={ru.sound.title}
        lead={ru.sound.lead}
        actions={
          <div className="flex flex-wrap gap-2">
            {canExport && (
              <Button asChild variant="outline">
                <a href="/api/subtitles.srt" download>
                  <Download size={18} aria-hidden />
                  {ru.exportPage.subtitlesButton}
                </a>
              </Button>
            )}
            {perms.canCreate && (
              <Button type="button" variant="outline" onClick={() => setAdding((v) => !v)}>
                <Plus size={18} />
                {ru.sound.addCue}
              </Button>
            )}
          </div>
        }
      />
      {adding && <NewCue cues={cues} onDone={() => setAdding(false)} />}
      <div className="mb-4">
        <FilterChips
          label={ru.sound.type}
          options={typeOptions}
          value={types}
          onToggle={(t) => setTypes((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))}
        />
      </div>
      {desktop ? (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[980px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-[0.12em] text-fog">
                <th className="px-3 py-2">{ru.sound.code}</th>
                <th className="px-2">{ru.sound.scene}</th>
                <th className="px-2">{ru.sound.shot}</th>
                <th className="px-2">{ru.sound.type}</th>
                <th className="px-2">{ru.sound.who}</th>
                <th className="px-2">{ru.sound.textEn}</th>
                <th className="px-2">{ru.sound.textRu}</th>
                <th className="px-2">{ru.sound.rights}</th>
                <th className="px-2">{ru.shots.status}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => {
                const { editable, save } = bind(c)
                return (
                  <tr key={c.id} data-cue={c.code} className="border-b border-line align-top">
                    <td className="mono whitespace-nowrap px-3 py-3 text-sm text-brass">{c.code}</td>
                    <td className="mono px-2 py-3 text-sm">{c.scene_number ?? ru.common.dash}</td>
                    <td className="w-28">
                      <EditableText value={c.shot_code} mono readOnly={!editable} ariaLabel={`${ru.sound.shot} ${c.code}`} onSave={(v) => saveShot(c, v)} />
                    </td>
                    <td className="w-36">
                      <EditableSelect value={c.type} allowEmpty={false} readOnly={!editable} ariaLabel={`${ru.sound.type} ${c.code}`} onChange={(v) => v && save({ type: v })} options={typeOptions} />
                    </td>
                    <td className="min-w-[140px]">
                      <EditableText value={c.who} readOnly={!editable} ariaLabel={`${ru.sound.who} ${c.code}`} onSave={(v) => save({ who: v })} />
                    </td>
                    <td className="min-w-[220px]">
                      <EditableText value={c.text_en} multiline readOnly={!editable} ariaLabel={`${ru.sound.textEn} ${c.code}`} onSave={(v) => save({ text_en: v })} />
                    </td>
                    <td className="min-w-[200px]">
                      <EditableText value={c.text_ru} multiline readOnly={!editable} ariaLabel={`${ru.sound.textRu} ${c.code}`} onSave={(v) => save({ text_ru: v })} />
                    </td>
                    <td className="min-w-[130px]">
                      <EditableText value={c.rights} readOnly={!editable} ariaLabel={`${ru.sound.rights} ${c.code}`} onSave={(v) => save({ rights: v })} />
                    </td>
                    <td className="px-2 py-3">{status(c)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <ul className="space-y-2">
          {visible.map((c) => (
            <li key={c.id} data-cue={c.code} className="space-y-1 rounded-xl border border-line bg-chart p-3">
              <div className="flex items-center gap-2 text-xs text-fog">
                <span className="mono text-sm font-semibold text-brass">{c.code}</span>
                <span>{ru.soundType[c.type as keyof typeof ru.soundType]}</span>
                {c.shot_code && <span className="mono">· {c.shot_code}</span>}
                <span className="flex-1" />
                {status(c)}
              </div>
              {c.who && <div className="text-sm font-semibold">{c.who}</div>}
              {c.text_en && <p className="text-sm">{c.text_en}</p>}
              {c.text_ru && <p className="text-xs text-fog">{c.text_ru}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
