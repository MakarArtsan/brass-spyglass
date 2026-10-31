import { Plus } from 'lucide-react'
import { useState } from 'react'
import { EditableSelect, EditableText } from '@/components/Editable'
import { PageHeader } from '@/components/PageHeader'
import { StatusPill } from '@/components/StatusPill'
import { Button } from '@/components/ui/button'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { usePerms } from '@/hooks/usePerms'
import { daysUntil } from '@/lib/format'
import { useCreate, useMeta, useTasks, useUpdate } from '@/lib/queries'
import type { StatusKey, Task } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const nextCode = (tasks: Task[] | undefined) => {
  const n = Math.max(0, ...(tasks ?? []).map((t) => Number(t.code.replace(/\D/g, '')) || 0)) + 1
  return `T-${String(n).padStart(2, '0')}`
}

function Due({ task }: { task: Task }) {
  if (!task.due_date) return <span className="text-xs text-fog">{ru.tasks.noDue}</span>
  const done = task.status === 'done' || task.status === 'cut'
  const days = daysUntil(task.due_date)
  const text = done ? '' : days < 0 ? ru.tasks.overdue(-days) : days === 0 ? ru.tasks.today : ru.tasks.inDays(days)
  return <span className={cn('text-xs', !done && days < 0 ? 'text-alert' : days <= 2 && !done ? 'text-brass-light' : 'text-fog')}>{text}</span>
}

function NewTask({ tasks, onDone }: { tasks: Task[] | undefined; onDone: () => void }) {
  const { data: meta } = useMeta()
  const create = useCreate<Task>('tasks')
  const [code, setCode] = useState(nextCode(tasks))
  const [title, setTitle] = useState('')
  const [block, setBlock] = useState('')
  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-chart p-3"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate({ code: code.trim(), title: title.trim(), block: block || null }, { onSuccess: onDone })
      }}
    >
      <label className="text-xs text-fog">
        {ru.tasks.code}
        <input value={code} onChange={(e) => setCode(e.target.value)} required maxLength={16} className="mono mt-1 block min-h-touch w-28 rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <label className="min-w-[220px] flex-1 text-xs text-fog">
        {ru.tasks.taskTitle}
        <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={500} className="mt-1 block min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <label className="text-xs text-fog">
        {ru.tasks.block}
        <select value={block} onChange={(e) => setBlock(e.target.value)} className="mt-1 block min-h-touch rounded-lg border border-line bg-ink px-2 text-sm text-paper">
          <option value="">{ru.common.dash}</option>
          {meta?.task_block.map((b) => (
            <option key={b} value={b}>
              {ru.taskBlock[b as keyof typeof ru.taskBlock]}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={!code.trim() || !title.trim() || create.isPending}>
        {ru.common.create}
      </Button>
      <Button type="button" variant="ghost" onClick={onDone}>
        {ru.common.cancel}
      </Button>
    </form>
  )
}

export default function Tasks() {
  const desktop = useIsDesktop()
  const perms = usePerms()
  const { data: tasks } = useTasks()
  const { data: meta } = useMeta()
  const update = useUpdate<Task>('tasks')
  const [block, setBlock] = useState('')
  const [hideDone, setHideDone] = useState(false)
  const [adding, setAdding] = useState(false)

  const blockOptions = (meta?.task_block ?? []).map((b) => ({ value: b, label: ru.taskBlock[b as keyof typeof ru.taskBlock] }))
  const priorityOptions = (meta?.priority ?? []).map((p) => ({ value: p, label: ru.priority[p as keyof typeof ru.priority] }))
  const visible = (tasks ?? [])
    .filter((t) => (block === '' || t.block === block) && !(hideDone && (t.status === 'done' || t.status === 'cut')))
    .sort((a, b) => (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999') || a.code.localeCompare(b.code))

  const statusPill = (t: Task) => (
    <StatusPill status={t.status} onChange={perms.canStatus ? (next: StatusKey) => update.mutate({ id: t.id, patch: { status: next } }) : undefined} />
  )

  return (
    <div>
      <PageHeader
        title={ru.tasks.title}
        lead={ru.tasks.lead}
        actions={
          perms.canCreate && (
            <Button type="button" variant="outline" onClick={() => setAdding((v) => !v)}>
              <Plus size={18} />
              {ru.tasks.addTask}
            </Button>
          )
        }
      />
      {adding && <NewTask tasks={tasks} onDone={() => setAdding(false)} />}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select value={block} onChange={(e) => setBlock(e.target.value)} aria-label={ru.tasks.block} className="min-h-touch rounded-lg border border-line bg-chart px-3 text-sm">
          <option value="">{ru.tasks.allBlocks}</option>
          {blockOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <label className="flex min-h-touch cursor-pointer items-center gap-2 text-sm text-fog">
          <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--brass))]" />
          {ru.tasks.hideDone}
        </label>
        <span className="mono ml-auto text-xs text-fog">{visible.length}</span>
      </div>

      {desktop ? (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[860px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-[0.12em] text-fog">
                <th className="px-3 py-2">{ru.tasks.code}</th>
                <th className="px-2">{ru.tasks.block}</th>
                <th className="px-2">{ru.tasks.task}</th>
                <th className="px-2">{ru.tasks.due}</th>
                <th className="px-2">{ru.shots.priority}</th>
                <th className="px-2">{ru.shots.status}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((t) => {
                const editable = perms.canEdit(t)
                const save = (patch: Record<string, unknown>) => update.mutate({ id: t.id, patch })
                return (
                  <tr key={t.id} data-task={t.code} className="border-b border-line align-middle">
                    <td className="mono px-3 text-sm text-brass">{t.code}</td>
                    <td className="w-40">
                      <EditableSelect value={t.block} readOnly={!editable} ariaLabel={`${ru.tasks.block} ${t.code}`} onChange={(v) => save({ block: v })} options={blockOptions} />
                    </td>
                    <td className="min-w-[280px]">
                      <EditableText value={t.title} multiline readOnly={!editable} ariaLabel={`${ru.tasks.task} ${t.code}`} onSave={(v) => v && save({ title: v })} />
                    </td>
                    <td className="w-44 px-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="date"
                          value={t.due_date ?? ''}
                          disabled={!editable}
                          aria-label={`${ru.tasks.due} ${t.code}`}
                          onChange={(e) => save({ due_date: e.target.value || null })}
                          className="mono min-h-touch rounded-md bg-transparent px-1 text-sm outline-none hover:bg-ink/60 focus:bg-ink disabled:opacity-100"
                        />
                        <Due task={t} />
                      </div>
                    </td>
                    <td className="w-36">
                      <EditableSelect value={t.priority} readOnly={!editable} ariaLabel={`${ru.shots.priority} ${t.code}`} onChange={(v) => save({ priority: v })} options={priorityOptions} />
                    </td>
                    <td className="w-40 px-2">{statusPill(t)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <ul className="space-y-2">
          {visible.map((t) => (
            <li key={t.id} data-task={t.code} className="space-y-1.5 rounded-xl border border-line bg-chart p-3">
              <div className="flex items-center gap-2 text-xs text-fog">
                <span className="mono text-sm font-semibold text-brass">{t.code}</span>
                {t.block && <span>{ru.taskBlock[t.block as keyof typeof ru.taskBlock]}</span>}
                <span className="flex-1" />
                {statusPill(t)}
              </div>
              <p className="text-sm">{t.title}</p>
              <div className="flex items-center gap-2 text-xs text-fog">
                {t.due_date && <span className="mono">{t.due_date.split('-').reverse().join('.')}</span>}
                <Due task={t} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
