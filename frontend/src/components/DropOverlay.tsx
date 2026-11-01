import { AnimatePresence, m as fm } from 'framer-motion'
import { motion } from '@/brand'
import { ru } from '@/ru'

/** Подсветка при перетаскивании файлов с компьютера. Отдельный чанк: нужна только при перетаскивании. */
export default function DropOverlay({ dragging, overZone }: { dragging: boolean; overZone: boolean }) {
  return (
    <AnimatePresence>
      {dragging && (
        <fm.div
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: motion.fast }}
          className="pointer-events-none fixed inset-2 z-[60] flex items-start justify-center rounded-2xl border-2 border-dashed border-brass bg-brass/5"
        >
          <span className="mt-6 rounded-full border border-brass bg-chart px-5 py-2 text-sm font-semibold text-brass-light">
            {overZone ? ru.files.drop : ru.files.dropHint}
          </span>
        </fm.div>
      )}
    </AnimatePresence>
  )
}
