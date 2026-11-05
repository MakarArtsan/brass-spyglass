import { lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { LensFilters } from '@/components/LensFilters'
import { useMe } from '@/hooks/useAuth'
import { ApiError } from '@/lib/api'
import { NAV } from '@/nav'
import { ru } from '@/ru'
import { currentSlug } from '@/lib/project'
import Login from '@/pages/Login'
import ProjectMissing from '@/pages/ProjectMissing'
import NewProject from '@/pages/NewProject'
import ProjectRequests from '@/pages/ProjectRequests'
import ProjectRedirect from '@/pages/ProjectRedirect'
import NotFound from '@/pages/NotFound'
import Placeholder from '@/pages/Placeholder'
import Dashboard from '@/pages/Dashboard'

// Страницы грузятся по требованию: на дашборде и экране входа не нужны dnd-kit, wavesurfer и т. д.
const Animatic = lazy(() => import('@/pages/Animatic'))
const Assets = lazy(() => import('@/pages/Assets'))
const Brand = lazy(() => import('@/pages/Brand'))
const Export = lazy(() => import('@/pages/Export'))
const ImportScenario = lazy(() => import('@/pages/ImportScenario'))
const Journal = lazy(() => import('@/pages/Journal'))
const Media = lazy(() => import('@/pages/Media'))
const SceneDetail = lazy(() => import('@/pages/SceneDetail'))
const Scenes = lazy(() => import('@/pages/Scenes'))
const Setups = lazy(() => import('@/pages/Setups'))
const Shots = lazy(() => import('@/pages/Shots'))
const Sound = lazy(() => import('@/pages/Sound'))
const Tasks = lazy(() => import('@/pages/Tasks'))
const Team = lazy(() => import('@/pages/Team'))
const Telegram = lazy(() => import('@/pages/Telegram'))

const IMPLEMENTED: Record<string, JSX.Element> = {
  '/': <Dashboard />,
  '/scenes': <Scenes />,
  '/shots': <Shots />,
  '/animatic': <Animatic />,
  '/export': <Export />,
  '/import': <ImportScenario />,
  '/media': <Media />,
  '/telegram': <Telegram />,
  '/assets': <Assets />,
  '/setups': <Setups />,
  '/sound': <Sound />,
  '/tasks': <Tasks />,
  '/journal': <Journal />,
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
  if (error instanceof ApiError && error.status === 401) {
    window.location.assign('/login')
    return null
  }
  if (error instanceof ApiError && error.status === 404) return <ProjectMissing />
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
        <Route path="/scenes/:id" element={<SceneDetail />} />
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
      {currentSlug ? (
        // Внутри проекта (`/p/<slug>/…`): роутер работает с basename проекта, ссылки остаются прежними.
        <Routes>
          <Route path="/*" element={<Protected />} />
        </Routes>
      ) : (
        // Вне проектов: вход и переход в свой проект (в том числе со старых ссылок вида `/shots`).
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/new-project" element={<NewProject />} />
          <Route path="/requests" element={<ProjectRequests />} />
          <Route path="/*" element={<ProjectRedirect />} />
        </Routes>
      )}
    </>
  )
}
