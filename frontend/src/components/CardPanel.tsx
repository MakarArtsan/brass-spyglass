import { AnimatePresence, m as fm } from 'framer-motion'
import { X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { motion } from '@/brand'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { ru } from '@/ru'

interface Props {
  open: boolean
  onClose: () => void
  title: ReactNode
  actions?: ReactNode
  children: ReactNode
}

/**
 * Карточка сущности (ТЗ): на ПК — боковая панель справа, список остаётся видимым;
 * на телефоне — лист снизу на весь экран, закрывается свайпом вниз.
 */
export function CardPanel({ open, onClose, title, actions, children }: Props) {
  const desktop = useIsDesktop()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      // Esc закрывает карточку, но не мешает закрытию вложенного диалога или меню
      if (e.key === 'Escape' && !document.querySelector('[role="dialog"][data-state="open"], [role="menu"]')) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (open) ref.current?.focus()
  }, [open])

  const header = (
    <div className="flex items-center gap-3 border-b border-line px-4 py-3">
      <div className="min-w-0 flex-1">{title}</div>
      {actions}
      <button
        type="button"
        onClick={onClose}
        aria-label={ru.common.close}
        className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog transition-colors duration-fast hover:bg-ink hover:text-paper"
      >
        <X size={20} />
      </button>
    </div>
  )

  return (
    <AnimatePresence>
      {open &&
        (desktop ? (
          <fm.aside
            key="side"
            ref={ref}
            tabIndex={-1}
            aria-label={typeof title === 'string' ? title : undefined}
            className="fixed bottom-0 right-0 top-0 z-30 flex w-[540px] flex-col border-l border-line bg-chart shadow-2xl shadow-black/50 outline-none"
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 40, opacity: 0 }}
            transition={{ duration: motion.base, ease: motion.ease }}
          >
            {header}
            <div className="flex-1 overflow-y-auto overscroll-contain">{children}</div>
          </fm.aside>
        ) : (
          <fm.div
            key="sheet"
            ref={ref}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label={typeof title === 'string' ? title : undefined}
            className="pb-safe pt-safe fixed inset-0 z-40 flex flex-col bg-chart outline-none"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ duration: motion.slow, ease: motion.ease }}
          >
            <fm.div
              drag="y"
              dragConstraints={{ top: 0, bottom: 0 }}
              dragElastic={{ top: 0, bottom: 0.6 }}
              onDragEnd={(_, info) => info.offset.y > 90 && onClose()}
              className="touch-none"
            >
              <span aria-hidden className="mx-auto mt-2 block h-1 w-10 rounded-full bg-line" />
              {header}
            </fm.div>
            <div className="flex-1 overflow-y-auto overscroll-contain">{children}</div>
          </fm.div>
        ))}
    </AnimatePresence>
  )
}
