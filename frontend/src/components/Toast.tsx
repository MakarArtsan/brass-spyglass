import { AnimatePresence, m as fm } from 'framer-motion'
import { useEffect, useState } from 'react'
import { motion } from '@/brand'
import { onToast } from '@/lib/toast'

interface Message {
  id: number
  text: string
}

/** Короткие уведомления: ошибки сохранения, подсказки. Исчезают через 4 секунды. */
export function Toaster() {
  const [items, setItems] = useState<Message[]>([])
  useEffect(
    () =>
      onToast((text) => {
        const id = Date.now() + Math.random()
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
      <AnimatePresence>
        {items.map((m) => (
          <fm.div
            key={m.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: motion.fast }}
            className="pointer-events-auto max-w-md rounded-lg border border-line bg-chart px-4 py-3 text-sm shadow-xl shadow-black/40"
          >
            {m.text}
          </fm.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
