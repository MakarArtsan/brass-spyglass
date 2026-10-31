import { Minus, Plus, RotateCcw } from 'lucide-react'
import { useRef, useState } from 'react'
import { ru } from '@/ru'

interface Props {
  src: string
  alt: string
  /** Горизонтальный свайп при масштабе 1× — переключение на соседний файл. */
  onSwipe: (direction: 1 | -1) => void
}

const MIN = 1
const MAX = 6

/** Лайтбокс фото: масштаб колесом и щипком, перетаскивание, двойной клик/тап — крупнее. */
export function ImageZoom({ src, alt, onSwipe }: Props) {
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })
  const [moving, setMoving] = useState(false) // во время жеста без плавной анимации
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const start = useRef({ distance: 0, scale: 1 })
  const swipe = useRef<{ x: number; y: number } | null>(null)

  const zoomTo = (scale: number, around?: { x: number; y: number }) =>
    setView((v) => {
      const next = Math.min(MAX, Math.max(MIN, scale))
      if (next === 1) return { scale: 1, x: 0, y: 0 }
      const k = next / v.scale
      const cx = around?.x ?? 0
      const cy = around?.y ?? 0
      return { scale: next, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k }
    })

  const relative = (e: React.PointerEvent | React.WheelEvent) => {
    const box = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: e.clientX - box.left - box.width / 2, y: e.clientY - box.top - box.height / 2 }
  }

  const onPointerDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    setMoving(true)
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      start.current = { distance: Math.hypot(a.x - b.x, a.y - b.y), scale: view.scale }
      swipe.current = null
    } else if (view.scale === 1) swipe.current = { x: e.clientX, y: e.clientY }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const prev = pointers.current.get(e.pointerId)
    if (!prev) return
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      const distance = Math.hypot(a.x - b.x, a.y - b.y)
      if (start.current.distance) zoomTo((start.current.scale * distance) / start.current.distance)
    } else if (view.scale > 1) {
      setView((v) => ({ ...v, x: v.x + e.clientX - prev.x, y: v.y + e.clientY - prev.y }))
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size === 0) setMoving(false)
    const s = swipe.current
    swipe.current = null
    if (s && view.scale === 1 && pointers.current.size === 0) {
      const dx = e.clientX - s.x
      if (Math.abs(dx) > 60 && Math.abs(e.clientY - s.y) < 50) onSwipe(dx < 0 ? 1 : -1)
    }
  }

  return (
    <div className="relative h-full w-full overflow-hidden">
      <div
        className="flex h-full w-full touch-none items-center justify-center"
        onWheel={(e) => zoomTo(view.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15), relative(e))}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={(e) => zoomTo(view.scale > 1 ? 1 : 2.5, relative(e as unknown as React.PointerEvent))}
        style={{ cursor: view.scale > 1 ? 'grab' : 'zoom-in' }}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          className="max-h-full max-w-full select-none object-contain"
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`, transition: moving ? 'none' : 'transform 150ms' }}
        />
      </div>
      <div className="absolute bottom-3 right-3 flex gap-1 rounded-xl bg-black/60 p-1">
        {[
          { label: ru.viewer.zoomOut, icon: <Minus size={18} />, run: () => zoomTo(view.scale / 1.5) },
          { label: ru.viewer.zoomReset, icon: <RotateCcw size={18} />, run: () => zoomTo(1) },
          { label: ru.viewer.zoomIn, icon: <Plus size={18} />, run: () => zoomTo(view.scale * 1.5) },
        ].map((b) => (
          <button
            key={b.label}
            type="button"
            aria-label={b.label}
            title={b.label}
            onClick={b.run}
            className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-paper hover:bg-white/10"
          >
            {b.icon}
          </button>
        ))}
      </div>
    </div>
  )
}
