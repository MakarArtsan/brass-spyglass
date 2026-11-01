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
import { ChevronRight, GripVertical, Plus, Search } from 'lucide-react'
import { Fragment, memo, useCallback, useMemo, useState } from 'react'
import { FilterChips } from '@/components/Chips'
import { CardPanel } from '@/components/CardPanel'
import { EditableSelect, EditableText } from '@/components/Editable'
import { Lens } from '@/components/Lens'
import { PageHeader } from '@/components/PageHeader'
import { ShotCard, ShotCardTitle } from '@/components/ShotCard'
import { StatusChip } from '@/components/StatusChip'
import { StatusPill } from '@/components/StatusPill'
import { dropZone } from '@/components/Uploads'
import { Button } from '@/components/ui/button'
import { STATUS_ORDER } from '@/brand'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { usePanelParam } from '@/hooks/usePanelParam'
import { usePerms } from '@/hooks/usePerms'
import { num, timecode } from '@/lib/format'
import { DashFilterBanner } from '@/components/DashFilterBanner'
import { useDashFilter } from '@/hooks/useDashFilter'
import { useBulkStatus, useCreate, useMeta, useReorder, useScenes, useShots, useUpdate } from '@/lib/queries'
import type { Meta } from '@/lib/types'
import { toast } from '@/lib/toast'
import type { Scene, Shot, StatusKey } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

/** Лимит одного клипа Seedance; та же граница, что у тревоги «шоты длиннее 15 сек» на дашборде. */
const LONG_SHOT_SEC = 15

const opts = (values: string[] | undefined, labels: Record<string, string>) =>
  (values ?? []).map((v) => ({ value: v, label: labels[v] ?? v }))

type Perms = ReturnType<typeof usePerms>
type Patch = (id: number, patch: Record<string, unknown>) => void

interface RowProps {
  perms: Perms
  meta: Meta | undefined
  patch: Patch
  shot: Shot
  selected: boolean
  onSelect: () => void
  onOpen: () => void
  dragEnabled: boolean
  active: boolean
}

/** Строка таблицы шот-листа: инлайн-правка ячеек, статус в один клик, перетаскивание за ручку. */
const ShotRow = memo(function ShotRow({ perms, meta, patch, shot, selected, onSelect, onOpen, dragEnabled, active }: RowProps) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: shot.id, disabled: !dragEnabled })
  const editable = perms.canEdit(shot)
  const save = (changes: Record<string, unknown>) => patch(shot.id, changes)

  return (
    <tr
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      {...(perms.canUpload ? dropZone({ entityType: 'shot', entityId: shot.id, purpose: 'reference' }) : {})}
      data-shot={shot.code}
      className={cn(
        'border-b border-line align-middle transition-colors duration-fast',
        isDragging && 'relative z-10 bg-chart shadow-xl',
        active && 'bg-brass/10',
        shot.status === 'cut' && 'opacity-60',
      )}
    >
      <td className="w-8 pl-1">
        {dragEnabled && (
          <button
            type="button"
            ref={setActivatorNodeRef}
            aria-label={`${ru.common.drag}: ${shot.code}`}
            {...attributes}
            {...listeners}
            className="flex min-h-touch min-w-[32px] cursor-grab touch-none items-center justify-center text-fog hover:text-paper active:cursor-grabbing"
          >
            <GripVertical size={16} />
          </button>
        )}
      </td>
      <td className="w-8 pr-1">
        <input type="checkbox" checked={selected} onChange={onSelect} aria-label={`${ru.common.selected(1)}: ${shot.code}`} className="h-4 w-4 cursor-pointer accent-[rgb(var(--brass))]" />
      </td>
      <td className="w-16 py-1 pl-2">
        <button type="button" onClick={onOpen} aria-label={`${ru.shots.card}: ${shot.code}`} className="group rounded-full outline-none focus-visible:ring-2 focus-visible:ring-brass">
          <Lens decorative size={40} src={shot.preview?.url} alt={shot.code}>
            <span className="block h-full w-full bg-ink" />
          </Lens>
        </button>
      </td>
      <td className="w-20">
        <button type="button" onClick={onOpen} className="mono min-h-touch px-1 text-sm font-semibold text-brass hover:text-brass-light">
          {shot.code}
        </button>
      </td>
      <td className="w-40 px-2">
        <StatusPill status={shot.status} onChange={perms.canStatus ? (status: StatusKey) => patch(shot.id, { status }) : undefined} />
      </td>
      <td className="min-w-[220px]">
        <EditableText value={shot.description} readOnly={!editable} multiline ariaLabel={`${ru.shots.description} ${shot.code}`} onSave={(v) => save({ description: v })} />
      </td>
      <td className="min-w-[120px]">
        <EditableSelect value={shot.size} readOnly={!editable} ariaLabel={`${ru.shots.size} ${shot.code}`} onChange={(v) => save({ size: v })} options={opts(meta?.size, ru.size)} />
      </td>
      <td className={'min-w-[130px]'}>
        <EditableText value={shot.camera} readOnly={!editable} ariaLabel={`${ru.shots.camera} ${shot.code}`} onSave={(v) => save({ camera: v })} />
      </td>
      <td className="w-20">
        <EditableText value={shot.duration_sec} numeric mono readOnly={!editable} ariaLabel={`${ru.shots.duration} ${shot.code}`} onSave={(v) => save({ duration_sec: v == null ? 0 : Number(v) })} />
      </td>
      <td className={'min-w-[130px] text-xs'}>
        <div className="flex flex-wrap gap-1 py-1">
          {shot.assets.map((a) => (
            <span key={a.asset_id} title={`${a.name}${a.state_name ? ` · ${a.state_name}` : ''}`} className="mono rounded bg-ink px-1.5 py-0.5 text-[11px] text-fog">
              {a.code}
            </span>
          ))}
        </div>
      </td>
      <td className={'min-w-[130px]'}>
        <EditableSelect value={shot.tool} readOnly={!editable} ariaLabel={`${ru.shots.tool} ${shot.code}`} onChange={(v) => save({ tool: v })} options={opts(meta?.tool, ru.tool)} />
      </td>
      <td className={'min-w-[130px]'}>
        <EditableSelect value={shot.stage} readOnly={!editable} ariaLabel={`${ru.shots.stage} ${shot.code}`} onChange={(v) => save({ stage: v })} options={opts(meta?.stage, ru.stage)} />
      </td>
      <td className={'mono w-14 text-center text-sm'}>{shot.takes_count || ru.common.dash}</td>
      <td className="w-8">
        <button type="button" onClick={onOpen} aria-label={`${ru.shots.card}: ${shot.code}`} className="flex min-h-touch min-w-[32px] items-center justify-center text-fog hover:text-paper">
          <ChevronRight size={18} />
        </button>
      </td>
    </tr>
  )
})

/** Карточка шота на телефоне: тап по чипу меняет статус, тап по карточке открывает лист. */
const ShotTile = memo(function ShotTile({ perms, patch, shot, onOpen, dragEnabled }: { perms: Perms; patch: Patch; shot: Shot; onOpen: () => void; dragEnabled: boolean }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: shot.id, disabled: !dragEnabled })
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      {...(perms.canUpload ? dropZone({ entityType: 'shot', entityId: shot.id, purpose: 'reference' }) : {})}
      data-shot={shot.code}
      className={cn('defer-render flex items-start gap-2 rounded-xl border border-line bg-chart p-2', isDragging && 'relative z-10 shadow-xl', shot.status === 'cut' && 'opacity-60')}
    >
      {dragEnabled && (
        <button type="button" ref={setActivatorNodeRef} aria-label={`${ru.common.drag}: ${shot.code}`} {...attributes} {...listeners} className="flex min-h-touch min-w-touch touch-none items-center justify-center text-fog">
          <GripVertical size={18} />
        </button>
      )}
      <button type="button" onClick={onOpen} className="group flex min-w-0 flex-1 items-start gap-3 text-left">
        <Lens decorative size={52} src={shot.preview?.url} alt={shot.code}>
          <span className="block h-full w-full bg-ink" />
        </Lens>
        <span className="min-w-0 flex-1">
          <span className="mono block text-sm font-semibold text-brass">{shot.code}</span>
          <span className="line-clamp-2 text-sm">{shot.description ?? ru.common.dash}</span>
          <span className="mt-1 block text-xs text-fog">
            {[shot.size ? ru.size[shot.size as keyof typeof ru.size] : null, `${num(shot.duration_sec)} ${ru.common.sec}`].filter(Boolean).join(' · ')}
          </span>
        </span>
      </button>
      <StatusPill status={shot.status} onChange={perms.canStatus ? (status: StatusKey) => patch(shot.id, { status }) : undefined} />
    </li>
  )
})

function NewShot({ scenes, onDone }: { scenes: Scene[]; onDone: () => void }) {
  const create = useCreate<Shot>('shots')
  const [sceneId, setSceneId] = useState(scenes[0]?.id ?? 0)
  const [code, setCode] = useState('')
  const [, openShot] = usePanelParam('shot')
  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-chart p-3"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate(
          { scene_id: sceneId, code: code.trim() },
          {
            onSuccess: (shot) => {
              onDone()
              openShot(shot.id)
            },
          },
        )
      }}
    >
      <label className="text-xs text-fog">
        {ru.shots.scene}
        <select value={sceneId} onChange={(e) => setSceneId(Number(e.target.value))} className="mt-1 block min-h-touch rounded-lg border border-line bg-ink px-2 text-sm text-paper">
          {scenes.map((s) => (
            <option key={s.id} value={s.id}>
              {s.number}. {s.title}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-fog">
        {ru.shots.newCode}
        <input value={code} onChange={(e) => setCode(e.target.value)} required pattern="\d{1,2}\.\d{1,3}" maxLength={16} placeholder="01.07" className="mono mt-1 block min-h-touch w-40 rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
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

export default function Shots() {
  const desktop = useIsDesktop()
  const perms = usePerms()
  const { data: shots } = useShots()
  const { data: scenes } = useScenes()
  const [openId, setOpenId] = usePanelParam('shot')
  const reorder = useReorder('shot')
  const bulk = useBulkStatus('shot')
  const { data: meta } = useMeta()
  const update = useUpdate<Shot>('shots')
  const patch = useCallback((id: number, changes: Record<string, unknown>) => update.mutate({ id, patch: changes }), [update])

  const [query, setQuery] = useState('')
  const [statuses, setStatuses] = useState<StatusKey[]>([])
  const [sceneFilter, setSceneFilter] = useState(0)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [adding, setAdding] = useState(false)
  const [filtersOpen, setFiltersOpen] = useState(false)

  const dash = useDashFilter()
  const filtersActive = query.trim() !== '' || statuses.length > 0 || sceneFilter !== 0 || dash.active
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const { status: dashStatus, long: dashLong, tool: dashTool } = dash
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase()
    const visible = (shots ?? []).filter(
      (s) =>
        (statuses.length === 0 || statuses.includes(s.status)) &&
        (dashStatus === null || dashStatus.includes(s.status)) &&
        (!dashLong || (s.status !== 'cut' && s.duration_sec > LONG_SHOT_SEC)) &&
        (dashTool === null || s.tool === dashTool) &&
        (sceneFilter === 0 || s.scene_id === sceneFilter) &&
        (q === '' || s.code.includes(q) || (s.description ?? '').toLowerCase().includes(q)),
    )
    const byScene = new Map<number, Shot[]>()
    for (const s of visible) byScene.set(s.scene_id, [...(byScene.get(s.scene_id) ?? []), s])
    return (scenes ?? []).filter((sc) => byScene.has(sc.id)).map((sc) => ({ scene: sc, shots: byScene.get(sc.id)! }))
  }, [shots, scenes, query, statuses, sceneFilter, dashStatus, dashLong, dashTool])

  const visibleIds = groups.flatMap((g) => g.shots.map((s) => s.id))
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))
  const dragEnabled = perms.canReorder && !filtersActive
  // Пока открыта карточка, таблице не хватает ширины — показываем компактные плитки, как на телефоне.
  const tiles = !desktop || openId != null
  const totalSec = (shots ?? []).filter((s) => s.status !== 'cut').reduce((a, s) => a + s.duration_sec, 0)

  const toggle = (id: number) =>
    setSelected((set) => {
      const next = new Set(set)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const onDragEnd = (group: { scene: Scene; shots: Shot[] }) => (e: DragEndEvent) => {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const ids = group.shots.map((s) => s.id)
    const next = arrayMove(ids, ids.indexOf(Number(active.id)), ids.indexOf(Number(over.id)))
    reorder.mutate({ ids: next, sceneId: group.scene.id }, { onError: () => toast(ru.scenes.reorderFailed) })
  }

  const statusOptions = STATUS_ORDER.map((s) => ({ value: s, label: ru.status[s], color: `rgb(var(--status-${s}))` }))

  return (
    <div className={cn('transition-[padding] duration-base', desktop && openId != null && 'lg:pr-[556px]')}>
      <PageHeader
        title={ru.shots.title}
        lead={ru.shots.lead}
        actions={
          perms.canCreate && (
            <Button type="button" variant="outline" onClick={() => setAdding((v) => !v)}>
              <Plus size={18} />
              {ru.shots.addShot}
            </Button>
          )
        }
      />
      <DashFilterBanner filter={dash} />
      {adding && scenes && <NewShot scenes={scenes} onDone={() => setAdding(false)} />}

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="relative">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fog" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={ru.shots.searchPlaceholder}
            aria-label={ru.shots.searchPlaceholder}
            className="min-h-touch w-64 rounded-lg border border-line bg-chart pl-9 pr-3 text-sm outline-none focus:border-brass"
          />
        </label>
        {!desktop && (
          <button
            type="button"
            aria-expanded={filtersOpen}
            onClick={() => setFiltersOpen((v) => !v)}
            className={cn('min-h-touch rounded-lg border px-3 text-sm', filtersActive ? 'border-brass text-brass-light' : 'border-line text-fog')}
          >
            {ru.shots.filtersButton}
            {filtersActive && ' •'}
          </button>
        )}
        <span className="mono ml-auto text-xs text-fog">{ru.shots.total(shots?.length ?? 0, totalSec)}</span>
      </div>
      {(desktop || filtersOpen) && (
        <div className="mb-4 space-y-3">
          <select value={sceneFilter} onChange={(e) => setSceneFilter(Number(e.target.value))} aria-label={ru.shots.scene} className="min-h-touch rounded-lg border border-line bg-chart px-3 text-sm">
            <option value={0}>{ru.shots.sceneFilter}</option>
            {scenes?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.number}. {s.title}
              </option>
            ))}
          </select>
          <FilterChips
            label={ru.shots.filters}
            options={statusOptions}
            value={statuses}
            onToggle={(s) => setStatuses((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))}
          />
        </div>
      )}

      {!tiles && selected.size > 0 && (
        <div role="region" aria-label={ru.common.applyStatus} className="sticky top-0 z-20 mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-brass bg-chart px-4 py-2 shadow-lg">
          <span className="text-sm font-semibold">{ru.common.selected(selected.size)}</span>
          <span className="text-xs text-fog">{ru.common.applyStatus}:</span>
          <div className="flex flex-wrap gap-1">
            {STATUS_ORDER.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => bulk.mutate({ ids: [...selected], status: s }, { onSuccess: () => setSelected(new Set()) })}
                className="min-h-touch rounded-full px-1 hover:opacity-80"
                aria-label={`${ru.common.applyStatus}: ${ru.status[s]}`}
              >
                <StatusChip status={s} />
              </button>
            ))}
          </div>
          <button type="button" onClick={() => setSelected(new Set())} className="ml-auto min-h-touch text-xs text-fog hover:text-paper">
            {ru.common.clearSelection}
          </button>
        </div>
      )}

      {shots && groups.length === 0 && <p className="py-12 text-center text-fog">{ru.shots.nothing}</p>}

      {!tiles ? (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[640px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-[0.12em] text-fog">
                <th className="w-8" />
                <th className="w-8">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(visibleIds))}
                    aria-label={ru.common.all}
                    className="h-4 w-4 cursor-pointer accent-[rgb(var(--brass))]"
                  />
                </th>
                <th className="w-14" />
                <th className="px-1 py-2">{ru.shots.code}</th>
                <th className="px-2">{ru.shots.status}</th>
                <th className="px-2">{ru.shots.description}</th>
                <th className="px-2">{ru.shots.size}</th>
                <th className="px-2">{ru.shots.camera}</th>
                <th className="px-2">{ru.shots.duration}</th>
                <th className="px-2">{ru.shots.assets}</th>
                <th className="px-2">{ru.shots.tool}</th>
                <th className="px-2">{ru.shots.stage}</th>
                <th className="px-2 text-center">{ru.shots.takes}</th>
                <th className="w-8" />
              </tr>
            </thead>
            {groups.map((group) => (
              <Fragment key={group.scene.id}>
                <tbody>
                  <tr className="bg-ink/60">
                    <td colSpan={14} className="px-3 py-2 font-display text-lg">
                      {group.scene.status === 'cut'
                        ? ru.shots.groupCut(group.scene.number, group.scene.title)
                        : ru.shots.groupHeader(group.scene.number, group.scene.title, timecode(group.scene.start_sec), timecode(group.scene.end_sec))}
                    </td>
                  </tr>
                </tbody>
                <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd(group)}>
                  <SortableContext items={group.shots.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                    <tbody>
                      {group.shots.map((shot) => (
                        <ShotRow
                          key={shot.id}
                          perms={perms}
                          meta={meta}
                          patch={patch}
                          shot={shot}
                          selected={selected.has(shot.id)}
                          onSelect={() => toggle(shot.id)}
                          onOpen={() => setOpenId(shot.id)}
                          dragEnabled={dragEnabled}
                          active={openId === shot.id}
                        />
                      ))}
                    </tbody>
                  </SortableContext>
                </DndContext>
              </Fragment>
            ))}
          </table>
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map((group) => (
            <section key={group.scene.id} aria-label={ru.scenes.scene(group.scene.number)}>
              <h2 className="mb-2 font-display text-xl">
                {group.scene.status === 'cut'
                  ? ru.shots.groupCut(group.scene.number, group.scene.title)
                  : ru.shots.groupHeader(group.scene.number, group.scene.title, timecode(group.scene.start_sec), timecode(group.scene.end_sec))}
              </h2>
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd(group)}>
                <SortableContext items={group.shots.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                  <ul className="space-y-2">
                    {group.shots.map((shot) => (
                      <ShotTile key={shot.id} perms={perms} patch={patch} shot={shot} onOpen={() => setOpenId(shot.id)} dragEnabled={dragEnabled} />
                    ))}
                  </ul>
                </SortableContext>
              </DndContext>
            </section>
          ))}
        </div>
      )}

      <CardPanel open={openId != null} onClose={() => setOpenId(null)} title={openId != null ? <ShotCardTitle shotId={openId} /> : ru.shots.card}>
        {openId != null && <ShotCard shotId={openId} />}
      </CardPanel>
    </div>
  )
}
