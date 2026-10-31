import { lazy, Suspense, useEffect, useState } from 'react'
import type { ToastMessage } from '@/components/ToastList'
import { onToast } from '@/lib/toast'

// Анимации тостов (framer-motion) грузятся отдельным чанком, когда появляется первый тост.
const ToastList = lazy(() => import('@/components/ToastList'))

/** Короткие уведомления: ошибки сохранения, подсказки. Исчезают через 4 секунды. */
export function Toaster() {
  const [items, setItems] = useState<ToastMessage[]>([])
  const [seen, setSeen] = useState(false) // после первого тоста список остаётся: нужен для плавного ухода
  useEffect(
    () =>
      onToast((text) => {
        const id = Date.now() + Math.random()
        setSeen(true)
        setItems((list) => [...list.slice(-3), { id, text }])
        window.setTimeout(() => setItems((list) => list.filter((m) => m.id !== id)), 4000)
      }),
    [],
  )
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-24 z-[70] flex flex-col items-center gap-2 px-4 lg:bottom-6"
    >
      {seen && (
        <Suspense fallback={null}>
          <ToastList items={items} />
        </Suspense>
      )}
    </div>
  )
}
