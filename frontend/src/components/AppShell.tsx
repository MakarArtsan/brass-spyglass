import { AnimatePresence, motion as fm } from 'framer-motion'
import { Suspense } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { motion } from '@/brand'
import { BottomNav } from '@/components/BottomNav'
import { ContestBadge } from '@/components/ContestBadge'
import { Header } from '@/components/Header'
import { Sidebar } from '@/components/Sidebar'
import { Toaster } from '@/components/Toast'
import { UploadProvider } from '@/components/Uploads'
import { useProject } from '@/hooks/useAuth'
import type { Me } from '@/lib/api'
import { useLiveUpdates } from '@/lib/live'
import { ru } from '@/ru'

/** ПК: левый сайдбар. Смартфон: нижняя панель. Одна и та же страница в двух раскладках. */
export function AppShell({ me }: { me: Me }) {
  const { data: project } = useProject()
  const location = useLocation()
  useLiveUpdates(true)
  return (
    <UploadProvider>
    <div className="min-h-dvh lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-brass focus:px-3 focus:py-2 focus:text-on-brass">
        К содержимому
      </a>
      <Sidebar user={me.user} abilities={me.abilities} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header project={project} />
        <main id="main" className="min-h-dvh flex-1 px-4 py-6 lg:px-8 lg:pb-10">
          <AnimatePresence mode="wait" initial={false}>
            <fm.div
              key={location.pathname}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: motion.fast, ease: motion.ease }}
            >
              <Suspense fallback={<div role="status" className="py-8 text-fog">{ru.app.loading}</div>}>
                <Outlet />
              </Suspense>
            </fm.div>
          </AnimatePresence>
        </main>
        <footer className="border-t border-line px-4 py-4 pb-24 lg:px-8 lg:pb-4">
          <ContestBadge />
        </footer>
      </div>
      <BottomNav user={me.user} abilities={me.abilities} />
      <Toaster />
    </div>
    </UploadProvider>
  )
}
