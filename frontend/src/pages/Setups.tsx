import { Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { EditableText } from '@/components/Editable'
import { Lens } from '@/components/Lens'
import { PageHeader } from '@/components/PageHeader'
import { StatusPill } from '@/components/StatusPill'
import { Button } from '@/components/ui/button'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { usePerms } from '@/hooks/usePerms'
import { useCreate, useSetups, useShots, useUpdate } from '@/lib/queries'
import { toast } from '@/lib/toast'
import type { Setup, Shot, StatusKey } from '@/lib/types'
import { ru } from '@/ru'

/** Коды шотов в ячейке («01.04, 11.03») → id. Неизвестный код — понятная ошибка, а не молчаливая потеря. */
function parseShots(text: string | null, shots: Shot[] | undefined): number[] | null {
  const byCode = new Map((shots ?? []).map((s) => [s.code, s.id]))
  const ids: number[] = []
  for (const token of (text ?? '').split(/[,;\s]+/).filter(Boolean)) {
    const id = byCode.get(token)
    if (id === undefined) {
      toast(`${ru.shots.code} «${token}»: ${ru.shots.nothing.toLowerCase()}`)
      return null
    }
    if (!ids.includes(id)) ids.push(id)
  }
  return ids
}

function ShotRefs({ refs, shots }: { refs: { id: number; code: string }[]; shots: Shot[] | undefined }) {
  const previews = refs.map((r) => shots?.find((s) => s.id === r.id)).filter((s): s is Shot => !!s)
  return (
    <div className="space-y-1.5">
      <div className="flex -space-x-2">
        {previews.slice(0, 4).map((s) => (
          <Link key={s.id} to={`/shots?shot=${s.id}`} className="group rounded-full outline-none focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-brass" aria-label={`${ru.shots.card}: ${s.code}`}>
            <Lens decorative size={34} src={s.preview?.url} alt={s.code}>
              <span className="block h-full w-full bg-ink" />
            </Lens>
          </Link>
        ))}
      </div>
      <div className="flex flex-wrap gap-1">
        {refs.map((r) => (
          <Link key={r.id} to={`/shots?shot=${r.id}`} className="mono flex min-h-touch items-center rounded border border-line px-2 text-xs hover:border-brass hover:text-brass-light">
            {r.code}
          </Link>
        ))}
      </div>
    </div>
  )
}

function NewSetup({ onDone }: { onDone: () => void }) {
  const create = useCreate<Setup>('setups')
  const [motif, setMotif] = useState('')
  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-chart p-3"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate({ motif: motif.trim() }, { onSuccess: onDone })
      }}
    >
      <label className="min-w-[240px] flex-1 text-xs text-fog">
        {ru.setups.motif}
        <input value={motif} onChange={(e) => setMotif(e.target.value)} required maxLength={300} className="mt-1 block min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <Button type="submit" disabled={!motif.trim() || create.isPending}>
        {ru.common.create}
      </Button>
      <Button type="button" variant="ghost" onClick={onDone}>
        {ru.common.cancel}
      </Button>
    </form>
  )
}

export default function Setups() {
  const desktop = useIsDesktop()
  const perms = usePerms()
  const { data: setups } = useSetups()
  const { data: shots } = useShots()
  const update = useUpdate<Setup>('setups')
  const [adding, setAdding] = useState(false)

  const cells = (s: Setup) => {
    const editable = perms.canEdit(s)
    const save = (patch: Record<string, unknown>) => update.mutate({ id: s.id, patch })
    const saveShots = (key: 'setup_shot_ids' | 'payoff_shot_ids') => (v: string | null) => {
      const ids = parseShots(v, shots)
      if (ids) save({ [key]: ids })
    }
    return { editable, save, saveShots }
  }
  const status = (s: Setup) => (
    <StatusPill status={s.status} onChange={perms.canStatus ? (next: StatusKey) => update.mutate({ id: s.id, patch: { status: next } }) : undefined} />
  )

  return (
    <div>
      <PageHeader
        title={ru.setups.title}
        lead={ru.setups.lead}
        actions={
          perms.canCreate && (
            <Button type="button" variant="outline" onClick={() => setAdding((v) => !v)}>
              <Plus size={18} />
              {ru.setups.addSetup}
            </Button>
          )
        }
      />
      {adding && <NewSetup onDone={() => setAdding(false)} />}
      {desktop ? (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[900px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-[0.12em] text-fog">
                <th className="w-12 px-3 py-2">{ru.setups.number}</th>
                <th className="px-2">{ru.setups.motif}</th>
                <th className="px-2">{ru.setups.setup}</th>
                <th className="px-2">{ru.setups.payoff}</th>
                <th className="px-2">{ru.setups.takeaway}</th>
                <th className="px-2">{ru.setups.risk}</th>
                <th className="px-2">{ru.shots.status}</th>
              </tr>
            </thead>
            <tbody>
              {setups?.map((s) => {
                const { editable, save, saveShots } = cells(s)
                return (
                  <tr key={s.id} data-setup={s.number} className="border-b border-line align-top">
                    <td className="mono px-3 py-3 text-sm text-brass">{s.number ?? ru.common.dash}</td>
                    <td className="min-w-[180px]">
                      <EditableText value={s.motif} readOnly={!editable} ariaLabel={ru.setups.motif} className="font-semibold" onSave={(v) => v && save({ motif: v })} />
                    </td>
                    <td className="min-w-[170px] px-2 py-2">
                      <ShotRefs refs={s.setup_shots} shots={shots} />
                      {editable && <EditableText value={s.setup_shots.map((x) => x.code).join(', ')} placeholder={ru.setups.shotsHint} ariaLabel={ru.setups.setup} className="text-xs text-fog" onSave={saveShots('setup_shot_ids')} mono />}
                    </td>
                    <td className="min-w-[170px] px-2 py-2">
                      <ShotRefs refs={s.payoff_shots} shots={shots} />
                      {editable && <EditableText value={s.payoff_shots.map((x) => x.code).join(', ')} placeholder={ru.setups.shotsHint} ariaLabel={ru.setups.payoff} className="text-xs text-fog" onSave={saveShots('payoff_shot_ids')} mono />}
                    </td>
                    <td className="min-w-[200px]">
                      <EditableText value={s.reader_takeaway} multiline readOnly={!editable} ariaLabel={ru.setups.takeaway} onSave={(v) => save({ reader_takeaway: v })} />
                    </td>
                    <td className="min-w-[200px]">
                      <EditableText value={s.risk} multiline readOnly={!editable} ariaLabel={ru.setups.risk} onSave={(v) => save({ risk: v })} />
                    </td>
                    <td className="px-2 py-3">{status(s)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <ul className="space-y-3">
          {setups?.map((s) => {
            const { editable, save } = cells(s)
            return (
              <li key={s.id} data-setup={s.number} className="space-y-3 rounded-xl border border-line bg-chart p-3">
                <div className="flex items-start gap-2">
                  <span className="mono text-lg font-semibold text-brass">{s.number}</span>
                  <div className="min-w-0 flex-1 font-semibold">
                    <EditableText value={s.motif} readOnly={!editable} ariaLabel={ru.setups.motif} onSave={(v) => v && save({ motif: v })} />
                  </div>
                  {status(s)}
                </div>
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-fog">{ru.setups.setup}</div>
                  <ShotRefs refs={s.setup_shots} shots={shots} />
                </div>
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-fog">{ru.setups.payoff}</div>
                  <ShotRefs refs={s.payoff_shots} shots={shots} />
                </div>
                {s.reader_takeaway && <p className="text-sm">{s.reader_takeaway}</p>}
                {s.risk && <p className="text-xs text-fog">{s.risk}</p>}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
