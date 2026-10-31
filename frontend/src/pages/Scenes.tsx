import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, Plus } from 'lucide-react'
import { useState } from 'react'
import { DashFilterBanner } from '@/components/DashFilterBanner'
import { useDashFilter } from '@/hooks/useDashFilter'
import { Link } from 'react-router-dom'
import { DrumLevel } from '@/components/DrumLevel'
import { PageHeader } from '@/components/PageHeader'
import { StatusPill } from '@/components/StatusPill'
import { Button } from '@/components/ui/button'
import { usePerms } from '@/hooks/usePerms'
import { num, timecode } from '@/lib/format'
import { useCreate, useReorder, useScenes, useUpdate } from '@/lib/queries'
import { toast } from '@/lib/toast'
import type { Scene, StatusKey } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

function SceneCard({ scene, dragEnabled }: { scene: Scene; dragEnabled: boolean }) {
  const perms = usePerms()
  const update = useUpdate<Scene>('scenes')
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: scene.id, disabled: !dragEnabled })
  const cut = scene.status === 'cut'
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-scene={scene.number}
      className={cn('flex items-start gap-2 rounded-xl border border-line bg-chart p-3 lg:gap-4 lg:p-4', isDragging && 'relative z-10 shadow-xl', cut && 'opacity-60')}
    >
      {dragEnabled && (
        <button type="button" ref={setActivatorNodeRef} aria-label={`${ru.common.drag}: ${ru.scenes.scene(scene.number)}`} {...attributes} {...listeners} className="flex min-h-touch min-w-touch cursor-grab touch-none items-center justify-center text-fog hover:text-paper active:cursor-grabbing">
          <GripVertical size={18} />
        </button>
      )}
      <Link to={`/scenes/${scene.id}`} className="min-w-0 flex-1 space-y-2 outline-none focus-visible:ring-2 focus-visible:ring-brass">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="mono text-2xl font-semibold text-brass">{String(scene.number).padStart(2, '0')}</span>
          <span className={cn('font-display text-2xl leading-tight', cut && 'line-through')}>{scene.title}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fog">
          <span className="mono text-paper" title={ru.scenes.timecode}>
            {cut ? ru.common.dash : `${timecode(scene.start_sec)}–${timecode(scene.end_sec)}`}
          </span>
          <span className="mono">
            {num(scene.planned_sec)} {ru.common.sec}
          </span>
          {scene.location && <span className="truncate">{scene.location}</span>}
          {scene.time_of_day && <span>{scene.time_of_day}</span>}
          <span className="flex items-center gap-1.5">
            {ru.scenes.drum}
            <DrumLevel level={scene.drum_level} />
          </span>
        </div>
        {scene.meaning && <p className="line-clamp-2 text-sm text-fog">{scene.meaning}</p>}
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-ink" role="progressbar" aria-valuenow={scene.ready_pct} aria-valuemin={0} aria-valuemax={100} aria-label={ru.scenes.shotsOf(scene.done_shots, scene.shots_count)}>
            <div className="h-full rounded-full bg-status-done" style={{ width: `${scene.ready_pct}%` }} />
          </div>
          <span className="text-fog">{ru.scenes.shotsOf(scene.done_shots, scene.shots_count)}</span>
          {Math.abs(scene.delta_sec) > 0.01 && <span className="text-status-in_progress">{ru.scenes.delta(scene.delta_sec)}</span>}
        </div>
      </Link>
      <StatusPill status={scene.status} onChange={perms.canStatus ? (status: StatusKey) => update.mutate({ id: scene.id, patch: { status } }) : undefined} />
    </li>
  )
}

function NewScene({ onDone, next }: { onDone: () => void; next: number }) {
  const create = useCreate<Scene>('scenes')
  const [number, setNumber] = useState(String(next))
  const [title, setTitle] = useState('')
  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-chart p-3"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate({ number: Number(number), title: title.trim() }, { onSuccess: onDone })
      }}
    >
      <label className="text-xs text-fog">
        №
        <input value={number} onChange={(e) => setNumber(e.target.value)} type="number" min={1} required className="mono mt-1 block min-h-touch w-24 rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <label className="min-w-[220px] flex-1 text-xs text-fog">
        {ru.scenes.sceneTitle}
        <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={300} className="mt-1 block min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <Button type="submit" disabled={!title.trim() || create.isPending}>
        {ru.common.create}
      </Button>
      <Button type="button" variant="ghost" onClick={onDone}>
        {ru.common.cancel}
      </Button>
    </form>
  )
}

export default function Scenes() {
  const perms = usePerms()
  const { data: scenes } = useScenes()
  const reorder = useReorder('scene')
  const [adding, setAdding] = useState(false)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const dash = useDashFilter()
  const ordered = [...(scenes ?? [])].sort((a, b) => a.order - b.order || a.id - b.id)
  // С фильтром виден неполный список: порядок по нему менять нельзя, иначе пересчитается по огрызку.
  const shown = dash.nofinal ? ordered.filter((s) => s.status !== 'cut' && s.final_file_id === null) : ordered

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const ids = ordered.map((s) => s.id)
    const next = arrayMove(ids, ids.indexOf(Number(active.id)), ids.indexOf(Number(over.id)))
    reorder.mutate({ ids: next }, { onError: () => toast(ru.scenes.reorderFailed) })
  }

  const planned = ordered.filter((s) => s.status !== 'cut').reduce((a, s) => a + s.planned_sec, 0)
  const byShots = ordered.filter((s) => s.status !== 'cut').reduce((a, s) => a + s.shots_sec, 0)

  return (
    <div>
      <PageHeader
        title={ru.scenes.title}
        lead={ru.scenes.lead}
        actions={
          perms.canCreate && (
            <Button type="button" variant="outline" onClick={() => setAdding((v) => !v)}>
              <Plus size={18} />
              {ru.scenes.addScene}
            </Button>
          )
        }
      />
      <DashFilterBanner filter={dash} />
      {adding && <NewScene onDone={() => setAdding(false)} next={Math.max(0, ...ordered.map((s) => s.number)) + 1} />}
      <p className="mono mb-3 text-xs text-fog">{ru.scenes.total(timecode(byShots), timecode(planned))}</p>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={shown.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          <ul className="space-y-3">
            {shown.map((scene) => (
              <SceneCard key={scene.id} scene={scene} dragEnabled={perms.canReorder && !dash.active} />
            ))}
          </ul>
        </SortableContext>
      </DndContext>
    </div>
  )
}
