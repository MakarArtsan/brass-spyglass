import { AnimatePresence, m as fm } from 'framer-motion'
import { X } from 'lucide-react'
import { useEffect } from 'react'
import { motion } from '@/brand'
import { NavGroups } from '@/components/Sidebar'
import { UserMenu } from '@/components/UserMenu'
import type { Abilities, User } from '@/lib/api'
import { ru } from '@/ru'

function MoreSheet({ user, abilities, onClose }: { user: User; abilities: Abilities; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <fm.div className="fixed inset-0 z-50 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: motion.fast }}>
      <button type="button" tabIndex={-1} aria-hidden className="absolute inset-0 bg-black/60" onClick={onClose} />
      <fm.div
        role="dialog"
        aria-modal="true"
        aria-label={ru.nav.more}
        className="pb-safe absolute inset-x-0 bottom-0 max-h-[85dvh] overflow-y-auto rounded-t-2xl border-t border-line bg-chart"
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ duration: motion.slow, ease: motion.ease }}
        drag="y"
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={{ top: 0, bottom: 0.5 }}
        onDragEnd={(_, info) => info.offset.y > 80 && onClose()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between bg-chart px-4 pb-1 pt-2">
          <span aria-hidden className="mx-auto h-1 w-10 rounded-full bg-line" />
          <button type="button" onClick={onClose} aria-label={ru.nav.close} className="absolute right-2 top-1 flex min-h-touch min-w-touch items-center justify-center text-fog">
            <X size={20} />
          </button>
        </div>
        <nav aria-label={ru.nav.more} className="flex flex-col gap-2 px-3 pb-2">
          <NavGroups abilities={abilities} onNavigate={onClose} skipPhoneItems columns={2} />
        </nav>
        <div className="border-t border-line p-4">
          <UserMenu user={user} />
        </div>
      </fm.div>
    </fm.div>
  )
}

/** Нижний лист «Ещё» с плавным выездом и закрытием свайпом вниз. Отдельный чанк: нужен только по нажатию. */
export default function MoreSheetHost({ open, user, abilities, onClose }: { open: boolean; user: User; abilities: Abilities; onClose: () => void }) {
  return <AnimatePresence>{open && <MoreSheet user={user} abilities={abilities} onClose={onClose} />}</AnimatePresence>
}
