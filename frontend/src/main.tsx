import '@fontsource/cormorant-garamond/cyrillic-600.css'
import '@fontsource/cormorant-garamond/latin-600.css'
import '@fontsource-variable/manrope/index.css'
import '@fontsource-variable/jetbrains-mono/index.css'
import './index.css'

import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from '@/App'
import { ThemeProvider } from '@/hooks/useTheme'
import { ApiError, api, type Me } from '@/lib/api'
import { meKey } from '@/hooks/useAuth'
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

if (!location.pathname.startsWith('/login')) {
  void queryClient.prefetchQuery({ queryKey: meKey, queryFn: () => api<Me>('/me'), staleTime: 60_000 })
  warmUpRoute(queryClient, location.pathname)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
