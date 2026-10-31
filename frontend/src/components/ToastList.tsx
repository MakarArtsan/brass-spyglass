import { AnimatePresence, m as fm } from 'framer-motion'
import { motion } from '@/brand'

export interface ToastMessage {
  id: number
  text: string
}

/** Плавное появление и исчезновение тостов. Отдельный чанк: framer-motion не нужен для первого показа. */
export default function ToastList({ items }: { items: ToastMessage[] }) {
  return (
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
  )
}
