import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { LensFilters } from '@/components/LensFilters'
import { useMe } from '@/hooks/useAuth'
import { ApiError } from '@/lib/api'
import { NAV } from '@/nav'
import { ru } from '@/ru'
import Brand from '@/pages/Brand'
import Dashboard from '@/pages/Dashboard'
import Login from '@/pages/Login'
import NotFound from '@/pages/NotFound'
import Placeholder from '@/pages/Placeholder'
import Team from '@/pages/Team'

const IMPLEMENTED: Record<string, JSX.Element> = {
  '/': <Dashboard />,
  '/team': <Team />,
}

function Protected() {
  const { data: me, error, isPending, refetch } = useMe()
  if (isPending) {
    return (
      <div role="status" className="flex min-h-dvh items-center justify-center text-fog">
        {ru.app.loading}
      </div>
    )
  }
  if (error instanceof ApiError && error.status === 401) return <Navigate to="/login" replace />
  if (error || !me) {
    return (
      <div role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-3">
        <p>{ru.app.error}</p>
        <button type="button" onClick={() => refetch()} className="min-h-touch rounded-lg border border-line px-4">
          {ru.app.retry}
        </button>
      </div>
    )
  }
  return (
    <Routes>
      <Route element={<AppShell me={me} />}>
        {NAV.map((item) => (
          <Route
            key={item.path}
            path={item.path}
            element={IMPLEMENTED[item.path] ?? <Placeholder path={item.path} />}
          />
        ))}
        <Route path="/brand" element={<Brand />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <>
      <LensFilters />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/*" element={<Protected />} />
      </Routes>
    </>
  )
}
