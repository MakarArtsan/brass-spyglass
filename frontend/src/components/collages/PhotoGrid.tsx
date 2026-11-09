import { ArrowLeft, ArrowRight, ImageOff, ImagePlus, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { MAX_PHOTOS } from '@/lib/collages'
import type { PhotoItem } from '@/lib/collagePhotos'
import { formatSize } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

/** Куда бросить или откуда выбрать фото; под ней — сколько выбрано. */
export function PhotoPicker({ count, busy, onAdd, compact = false }: { count: number; busy: boolean; onAdd: (list: FileList | null) => void; compact?: boolean }) {
  const [over, setOver] = useState(false)
  const picker = useRef<HTMLInputElement>(null)
  const pick = (list: FileList | null) => {
    onAdd(list)
    if (picker.current) picker.current.value = ''
  }
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        if (!busy) pick(e.dataTransfer.files)
      }}
      className={cn(
        'flex flex-col items-center gap-2 rounded-xl border border-dashed text-center transition-colors duration-fast',
        compact ? 'p-3' : 'p-5',
        over ? 'border-brass bg-brass/10' : 'border-line',
      )}
    >
      <ImagePlus size={compact ? 20 : 24} className="text-brass" aria-hidden />
      <p className="text-sm">{compact ? ru.collages.dropMore : ru.collages.drop}</p>
      <Button type="button" variant="outline" disabled={busy || count >= MAX_PHOTOS} onClick={() => picker.current?.click()}>
        {compact ? ru.collages.addPhotos : ru.collages.pick}
      </Button>
      <input
        ref={picker}
        type="file"
        multiple
        accept="image/*,.heic,.heif,.avif"
        className="sr-only"
        aria-label={ru.collages.pickInput}
        onChange={(e) => pick(e.target.files)}
      />
      <p className="text-xs text-fog" aria-live="polite">
        {ru.collages.count(count, MAX_PHOTOS)}
      </p>
    </div>
  )
}

/** Фото по порядку раскладки: номер, превью, имя, состояние и кнопки «раньше», «позже», «убрать». */
export function PhotoGrid({
  items,
  busy,
  onMove,
  onRemove,
  onBroken,
}: {
  items: PhotoItem[]
  busy: boolean
  onMove: (index: number, by: -1 | 1) => void
  onRemove: (key: string) => void
  onBroken: (key: string) => void
}) {
  if (items.length === 0) return null
  return (
    <ol aria-label={ru.collages.photosLabel} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {items.map((item, index) => (
        <li key={item.key} className="overflow-hidden rounded-xl border border-line bg-ink">
          <div className="relative aspect-[4/3] bg-ink">
            {item.broken || !item.preview ? (
              <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-fog">
                <ImageOff size={22} aria-hidden />
                <span className="text-[10px]">{ru.collages.noPreview}</span>
              </div>
            ) : (
              <img src={item.preview} alt={item.name} className="h-full w-full object-contain" onError={() => onBroken(item.key)} />
            )}
            <span className="mono absolute left-1.5 top-1.5 rounded bg-ink/80 px-1.5 text-xs text-brass">{index + 1}</span>
            {item.status === 'uploading' && (
              <div className="absolute inset-x-0 bottom-0 h-1.5 bg-ink/70" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(item.progress * 100)}>
                <div className="h-full bg-brass transition-[width] duration-base" style={{ width: `${Math.max(4, item.progress * 100)}%` }} />
              </div>
            )}
          </div>
          <div className="px-2 pb-1 pt-1.5">
            <p className="truncate text-xs" title={item.name}>
              {item.name}
            </p>
            <p className={cn('text-[11px]', item.status === 'error' ? 'text-alert' : 'text-fog')}>
              {item.status === 'done' ? ru.collages.uploaded : item.status === 'error' ? ru.collages.itemFailed : item.file ? formatSize(item.size) : ru.collages.inProject(formatSize(item.size))}
            </p>
          </div>
          <div className="flex items-center justify-between px-1 pb-1">
            <button
              type="button"
              aria-label={ru.collages.moveLeft(item.name)}
              disabled={busy || index === 0}
              onClick={() => onMove(index, -1)}
              className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:text-paper disabled:opacity-30"
            >
              <ArrowLeft size={18} aria-hidden />
            </button>
            <button
              type="button"
              aria-label={ru.collages.moveRight(item.name)}
              disabled={busy || index === items.length - 1}
              onClick={() => onMove(index, 1)}
              className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:text-paper disabled:opacity-30"
            >
              <ArrowRight size={18} aria-hidden />
            </button>
            <button
              type="button"
              aria-label={ru.collages.removePhoto(item.name)}
              disabled={busy}
              onClick={() => onRemove(item.key)}
              className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:text-alert disabled:opacity-30"
            >
              <X size={18} aria-hidden />
            </button>
          </div>
        </li>
      ))}
    </ol>
  )
}
