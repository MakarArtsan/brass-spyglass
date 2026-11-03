import '@fontsource/cormorant-garamond/cyrillic-600.css'
import '@fontsource/cormorant-garamond/latin-600.css'
import '@fontsource-variable/manrope/index.css'
import '@fontsource-variable/jetbrains-mono/index.css'
import './index.css'

import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LazyMotion } from 'framer-motion'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from '@/App'
import { ThemeProvider } from '@/hooks/useTheme'
import { ApiError, api, type Me } from '@/lib/api'
import { meKey } from '@/hooks/useAuth'
import { loadMotionFeatures } from '@/lib/motionLoader'
import { currentSlug, innerPath, rememberProject } from '@/lib/project'
import { warmUpRoute } from '@/lib/queries'
import { toast } from '@/lib/toast'
import { ru } from '@/ru'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
  mutationCache: new MutationCache({
    // Понятная причина от сервера («Недостаточно прав», «код уже занят») вместо молчаливого отката.
    onError: (error) => toast(error instanceof ApiError ? error.message : ru.common.saveFailed),
  }),
})

if (currentSlug) {
  rememberProject(currentSlug)
  void queryClient.prefetchQuery({ queryKey: meKey, queryFn: () => api<Me>('/me'), staleTime: 60_000 })
  warmUpRoute(queryClient, innerPath(location.pathname))
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        {/* Лёгкие m-компоненты в начальном наборе, сами возможности — отдельным чанком позже. */}
        <LazyMotion features={loadMotionFeatures} strict>
          {/* Внутри проекта все пути приложения (`/shots`) живут под `/p/<slug>`: это basename роутера. */}
          <BrowserRouter basename={currentSlug ? `/p/${encodeURIComponent(currentSlug)}` : undefined}>
            <App />
          </BrowserRouter>
        </LazyMotion>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
