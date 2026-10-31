import type { FeatureBundle } from 'framer-motion'

const AFTER_LOAD_MS = 1500

/**
 * Анимации и жесты (31 КБ) нужны не для первого показа, а для листов, тостов и перетаскивания.
 * Грузим их, когда страница уже загрузилась и поток свободен, чтобы не мешать первой отрисовке.
 */
export function loadMotionFeatures(): Promise<FeatureBundle> {
  return new Promise((resolve) => {
    const start = () => {
      const go = () => void import('@/lib/motionFeatures').then((module) => resolve(module.default))
      window.setTimeout(() => {
        if ('requestIdleCallback' in window) window.requestIdleCallback(go, { timeout: 3000 })
        else go()
      }, AFTER_LOAD_MS)
    }
    if (document.readyState === 'complete') start()
    else window.addEventListener('load', start, { once: true })
  })
}
