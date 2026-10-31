import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  src?: string
  /** Только украшение: эффект по наведению родителя (`group`), клик и фокус не перехватываем. */
  decorative?: boolean
  alt: string
  /** Диаметр окуляра, px. */
  size?: number
  className?: string
  children?: ReactNode
}

/**
 * Превью в круглой рамке-окуляре с латунным ободом. Эффект «через трубу»
 * (бочкообразная дисторсия, золотой тон, виньетка) включается:
 *  — мышью: наведением;
 *  — касанием и стилусом: тапом, повторный тап выключает («только по наведению» на телефоне не бывает);
 *  — с клавиатуры: фокусом или Enter/Пробелом.
 */
export function Lens({ src, alt, decorative, size = 96, className, children }: Props) {
  const [tube, setTube] = useState(false)
  const pointer = useRef<string>('')

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setTube((v) => !v)
    }
  }

  if (decorative) {
    return (
      <span aria-hidden className={cn('lens lens-decor', className)} style={{ width: size, height: size }}>
        {src ? <img src={src} alt="" draggable={false} className="lens-img" /> : children}
        <span className="lens-glass" aria-hidden />
      </span>
    )
  }
  return (
    <span
      role="img"
      aria-label={alt}
      tabIndex={0}
      data-tube={tube}
      className={cn('lens cursor-pointer', className)}
      style={{ width: size, height: size }}
      onPointerDown={(e) => (pointer.current = e.pointerType)}
      onPointerEnter={(e) => e.pointerType === 'mouse' && setTube(true)}
      onPointerLeave={(e) => e.pointerType === 'mouse' && setTube(false)}
      // Тап сперва ставит фокус, потом шлёт click: фокус от касания игнорируем (он не :focus-visible).
      onClick={() => pointer.current !== 'mouse' && pointer.current !== '' && setTube((v) => !v)}
      onFocus={(e) => e.currentTarget.matches(':focus-visible') && setTube(true)}
      onBlur={() => setTube(false)}
      onKeyDown={onKeyDown}
    >
      {src ? <img src={src} alt="" draggable={false} className="lens-img" /> : children}
      <span className="lens-glass" aria-hidden />
    </span>
  )
}
