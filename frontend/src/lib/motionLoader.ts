import type { FeatureBundle } from 'framer-motion'

const AFTER_LOAD_MS = 1500
/** Первое касание, прокрутка или клавиша — признак, что человек вот-вот нажмёт «Ещё»: не ждём таймера. */
const INTERACTION_EVENTS = ['pointerdown', 'keydown', 'scroll'] as const

/**
 * Анимации и жесты (31 КБ) нужны не для первого показа, а для листов, тостов и перетаскивания.
 * Грузим их, когда страница уже загрузилась и поток свободен, чтобы не мешать первой отрисовке,
 * а если человек начал пользоваться страницей раньше — сразу.
 */
export function loadMotionFeatures(): Promise<FeatureBundle> {
  return new Promise((resolve) => {
    let started = false
    const go = () => {
      if (started) return
      started = true
      void import('@/lib/motionFeatures').then((module) => resolve(module.default))
      // Ленивые куски с анимациями грузим заранее: первое нажатие «Ещё», тост и перетаскивание не ждут сеть.
      void import('@/components/MoreSheetHost')
      void import('@/components/ToastList')
      void import('@/components/DropOverlay')
    }
    const start = () => {
      const timer = window.setTimeout(() => {
        if ('requestIdleCallback' in window) window.requestIdleCallback(go, { timeout: 3000 })
        else go()
      }, AFTER_LOAD_MS)
      const now = () => {
        window.clearTimeout(timer)
        go()
      }
      for (const type of INTERACTION_EVENTS) {
        window.addEventListener(type, now, { once: true, passive: true, capture: true })
      }
    }
    if (document.readyState === 'complete') start()
    else window.addEventListener('load', start, { once: true })
  })
}
