import { useLayoutEffect, useEffect, useRef, useState, type RefObject } from 'react'
import { motion } from '@/brand'

/** Графики «рисуются» при загрузке: значение приходит на следующем кадре, а CSS плавно доводит. */
export function useAppear(): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setOn(true))
    return () => cancelAnimationFrame(id)
  }, [])
  return on
}

/** Длительность анимации графиков — те же 250 мс, что у остального интерфейса. */
export const chartTransition = {
  transitionDuration: `${motion.slow}s`,
  transitionTimingFunction: `cubic-bezier(${motion.ease.join(',')})`,
}

/** Точка на окружности: 180° — слева, 90° — сверху, 0° — справа. */
export function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = (deg * Math.PI) / 180
  return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)]
}

/** Дуга полукруга между двумя долями шкалы 0…1 (слева направо поверх центра). */
export function arcPath(cx: number, cy: number, r: number, from: number, to: number): string {
  const [x1, y1] = polar(cx, cy, r, 180 - 180 * from)
  const [x2, y2] = polar(cx, cy, r, 180 - 180 * to)
  const large = (to - from) * 180 > 180 ? 1 : 0
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`
}

/** Ширина контейнера в пикселях: графики рисуются в натуральном размере, и текст не сжимается. */
export function useWidth<T extends HTMLElement>(fallback = 320): [RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const update = () => setWidth(Math.max(200, Math.round(el.clientWidth)))
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}
