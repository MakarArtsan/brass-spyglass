import { useMemo } from 'react'

/**
 * Карта смещения для бочкообразной дисторсии: R и G растут как x³ и y³ от центра.
 * Считается один раз на canvas 64×64 — никакого WebGL, только SVG-фильтр.
 */
function barrelMap(size = 64): string {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  const img = ctx.createImageData(size, size)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const nx = (x / (size - 1)) * 2 - 1
      const ny = (y / (size - 1)) * 2 - 1
      const i = (y * size + x) * 4
      img.data[i] = 128 + 127 * Math.sign(nx) * Math.abs(nx) ** 3
      img.data[i + 1] = 128 + 127 * Math.sign(ny) * Math.abs(ny) ** 3
      img.data[i + 2] = 128
      img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
  return canvas.toDataURL()
}

/** Один раз на страницу: определяет фильтр `#lens-barrel`, который использует <Lens>. */
export function LensFilters() {
  const map = useMemo(() => barrelMap(), [])
  return (
    <svg width="0" height="0" aria-hidden focusable="false" className="pointer-events-none absolute">
      <filter
        id="lens-barrel"
        x="0"
        y="0"
        width="1"
        height="1"
        primitiveUnits="objectBoundingBox"
        colorInterpolationFilters="sRGB"
      >
        <feImage href={map} x="0" y="0" width="1" height="1" preserveAspectRatio="none" result="map" />
        <feDisplacementMap in="SourceGraphic" in2="map" scale="0.14" xChannelSelector="R" yChannelSelector="G" />
      </filter>
    </svg>
  )
}
