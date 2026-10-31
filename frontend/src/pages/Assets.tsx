import { Box, Drama, MapPin, PawPrint, Palette, Plus, Search, Ship, User, Users, Wind, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { AssetCard, AssetCardTitle } from '@/components/AssetCard'
import { CardPanel } from '@/components/CardPanel'
import { FilterChips } from '@/components/Chips'
import { Lens } from '@/components/Lens'
import { PageHeader } from '@/components/PageHeader'
import { StatusPill } from '@/components/StatusPill'
import { dropZone } from '@/components/Uploads'
import { Button } from '@/components/ui/button'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { usePanelParam } from '@/hooks/usePanelParam'
import { usePerms } from '@/hooks/usePerms'
import { useAssets, useCreate, useMeta, useUpdate } from '@/lib/queries'
import type { Asset, StatusKey } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const ICONS: Record<string, LucideIcon> = {
  character: User,
  crowd: Users,
  animal: PawPrint,
  prop: Box,
  faux_prop: Drama,
  location: MapPin,
  ship: Ship,
  effect: Wind,
  style: Palette,
}

function AssetTile({ asset, active, onOpen }: { asset: Asset; active: boolean; onOpen: () => void }) {
  const perms = usePerms()
  const update = useUpdate<Asset>('assets')
  const Icon = ICONS[asset.type] ?? Box
  return (
    <li
      {...(perms.canUpload ? dropZone({ entityType: 'asset', entityId: asset.id, purpose: 'reference' }) : {})}
      data-asset={asset.code}
      className={cn('space-y-2 rounded-xl border border-line bg-chart p-3', active && 'border-brass')}
    >
      <button type="button" onClick={onOpen} aria-label={`${ru.assets.card}: ${asset.code}`} className="group flex min-w-0 flex-1 items-start gap-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-brass">
        <Lens decorative size={64} src={asset.preview?.url} alt={asset.name}>
          <span className="flex h-full w-full items-center justify-center bg-ink text-brass">
            <Icon size={24} />
          </span>
        </Lens>
        <span className="min-w-0 flex-1">
          <span className="mono block text-sm font-semibold text-brass">{asset.code}</span>
          <span className="line-clamp-2 text-sm">{asset.name}</span>
          <span className="mt-1 block text-xs text-fog">
            {ru.assetType[asset.type as keyof typeof ru.assetType]} ·{' '}
            <span className={asset.shots_count === 0 ? 'text-status-rework' : undefined}>{ru.assets.shotsCount(asset.shots_count)}</span>
            {asset.states.length > 0 && ` · ${ru.assets.states.toLowerCase()}: ${asset.states.length}`}
          </span>
        </span>
      </button>
      <div className="pl-[76px]">
        <StatusPill status={asset.status} onChange={perms.canStatus ? (status: StatusKey) => update.mutate({ id: asset.id, patch: { status } }) : undefined} />
      </div>
    </li>
  )
}

function NewAsset({ onDone }: { onDone: () => void }) {
  const { data: meta } = useMeta()
  const create = useCreate<Asset>('assets')
  const [, open] = usePanelParam('asset')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [type, setType] = useState('character')
  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-chart p-3"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate(
          { code: code.trim(), name: name.trim(), type },
          {
            onSuccess: (asset) => {
              onDone()
              open(asset.id)
            },
          },
        )
      }}
    >
      <label className="text-xs text-fog">
        {ru.assets.code}
        <input value={code} onChange={(e) => setCode(e.target.value)} required maxLength={16} placeholder="CH-14" className="mono mt-1 block min-h-touch w-28 rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <label className="min-w-[200px] flex-1 text-xs text-fog">
        {ru.assets.name}
        <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={300} className="mt-1 block min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass" />
      </label>
      <label className="text-xs text-fog">
        {ru.assets.type}
        <select value={type} onChange={(e) => setType(e.target.value)} className="mt-1 block min-h-touch rounded-lg border border-line bg-ink px-2 text-sm text-paper">
          {meta?.asset_type.map((t) => (
            <option key={t} value={t}>
              {ru.assetType[t as keyof typeof ru.assetType]}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={!code.trim() || !name.trim() || create.isPending}>
        {ru.common.create}
      </Button>
      <Button type="button" variant="ghost" onClick={onDone}>
        {ru.common.cancel}
      </Button>
    </form>
  )
}

export default function Assets() {
  const desktop = useIsDesktop()
  const perms = usePerms()
  const { data: assets } = useAssets()
  const { data: meta } = useMeta()
  const [openId, setOpenId] = usePanelParam('asset')
  const [types, setTypes] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [adding, setAdding] = useState(false)
  const [filtersOpen, setFiltersOpen] = useState(false)

  const q = query.trim().toLowerCase()
  const visible = (assets ?? []).filter(
    (a) => (types.length === 0 || types.includes(a.type)) && (q === '' || a.code.toLowerCase().includes(q) || a.name.toLowerCase().includes(q)),
  )
  const compact = desktop && openId != null

  return (
    <div className={cn('transition-[padding] duration-base', compact && 'lg:pr-[556px]')}>
      <PageHeader
        title={ru.assets.title}
        lead={ru.assets.lead}
        actions={
          perms.canCreate && (
            <Button type="button" variant="outline" onClick={() => setAdding((v) => !v)}>
              <Plus size={18} />
              {ru.assets.addAsset}
            </Button>
          )
        }
      />
      {adding && <NewAsset onDone={() => setAdding(false)} />}
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="relative">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fog" aria-hidden />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={ru.assets.searchPlaceholder} aria-label={ru.assets.searchPlaceholder} className="min-h-touch w-64 rounded-lg border border-line bg-chart pl-9 pr-3 text-sm outline-none focus:border-brass" />
        </label>
        {!desktop && (
          <button type="button" aria-expanded={filtersOpen} onClick={() => setFiltersOpen((v) => !v)} className={cn('min-h-touch rounded-lg border px-3 text-sm', types.length ? 'border-brass text-brass-light' : 'border-line text-fog')}>
            {ru.shots.filtersButton}
            {types.length > 0 && ' •'}
          </button>
        )}
        <span className="mono ml-auto text-xs text-fog">{visible.length}</span>
      </div>
      <div className={cn('mb-4', !desktop && !filtersOpen && 'hidden')}>
        <FilterChips
          label={ru.assets.type}
          options={(meta?.asset_type ?? []).map((t) => ({ value: t, label: ru.assetType[t as keyof typeof ru.assetType] }))}
          value={types}
          onToggle={(t) => setTypes((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))}
        />
      </div>
      <ul className={cn('grid gap-3', compact ? 'grid-cols-1' : 'sm:grid-cols-2 xl:grid-cols-3')}>
        {visible.map((a) => (
          <AssetTile key={a.id} asset={a} active={openId === a.id} onOpen={() => setOpenId(a.id)} />
        ))}
      </ul>
      <CardPanel open={openId != null} onClose={() => setOpenId(null)} title={openId != null ? <AssetCardTitle assetId={openId} /> : ru.assets.card}>
        {openId != null && <AssetCard assetId={openId} />}
      </CardPanel>
    </div>
  )
}
