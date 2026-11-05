import { Link } from 'react-router-dom'
import { ActivityTile } from '@/components/dashboard/Activity'
import { BurndownTile } from '@/components/dashboard/Burndown'
import { Readiness, RuntimeGauge, SeedanceGauge } from '@/components/dashboard/Gauges'
import { AlertsTile, ContributionTile, FeedTile, MediaTile, MyTasksTile, SavedTile } from '@/components/dashboard/Lists'
import { Deferred } from '@/components/dashboard/primitives'
import { DrumCurve, FilmStrip } from '@/components/dashboard/Strip'
import { useMe } from '@/hooks/useAuth'
import { useDashboard } from '@/lib/dashboard'
import { ru } from '@/ru'

/**
 * Плитки дашборда. Отдельный чанк: страница с заголовком и сроками рисуется, не дожидаясь графиков.
 * Возвращает элементы сетки страницы (`lg:col-span-*`), поэтому встаёт прямо в неё.
 */
export default function DashboardTiles() {
  const { data: me } = useMe()
  const { data: dash, isError, refetch } = useDashboard()
  if (!me) return null
  return (
    <>
      {!dash && !isError && <div aria-hidden role="status" className="min-h-[900px] lg:col-span-12" />}
        {isError && (
          <div role="alert" className="panel flex items-center justify-between gap-3 p-4 lg:col-span-12">
            <span className="text-alert">{ru.dash.error}</span>
            <button type="button" onClick={() => void refetch()} className="min-h-[44px] rounded-lg border border-line px-4 text-sm hover:border-brass/60">
              {ru.dash.retry}
            </button>
          </div>
        )}
        {dash && (
          <>
            {me.abilities.import_scenario && dash.film_strip.length === 0 && dash.readiness.shots.total === 0 && dash.readiness.assets.total === 0 && (
              <div className="panel flex flex-wrap items-center gap-x-6 gap-y-3 p-4 lg:col-span-12">
                <div className="min-w-0 flex-1">
                  <h2 className="text-xl">{ru.dash.emptyProject}</h2>
                  <p className="text-sm text-fog">{ru.dash.emptyProjectLead}</p>
                </div>
                <Link to="/import" className="inline-flex min-h-touch items-center rounded-lg bg-brass px-4 text-sm font-semibold text-on-brass hover:bg-brass-light">
                  {ru.dash.emptyProjectAction}
                </Link>
              </div>
            )}
            <div className="lg:col-span-7">
              <Readiness data={dash.readiness} />
            </div>
            <div className="lg:col-span-4">
              <Deferred title={ru.dash.runtime} minHeight={300}>
                <RuntimeGauge data={dash.runtime} />
              </Deferred>
            </div>
            <div className="lg:col-span-4">
              <Deferred title={ru.dash.seedance} minHeight={290}>
                <SeedanceGauge data={dash.seedance} />
              </Deferred>
            </div>
            <div className="space-y-4 lg:col-span-4">
              <Deferred title={ru.dash.media} minHeight={290}>
                <MediaTile data={dash.media} />
              </Deferred>
              <Deferred title={ru.dash.saved} minHeight={110}>
                <SavedTile data={dash.media} />
              </Deferred>
            </div>
            <div className="lg:col-span-7">
              <Deferred title={ru.dash.burndown} minHeight={380}>
                <BurndownTile data={dash.burndown} />
              </Deferred>
            </div>
            <div className="lg:col-span-5">
              <Deferred title={ru.dash.alerts} minHeight={270}>
                <AlertsTile data={dash.alerts} />
              </Deferred>
            </div>
            <div className="lg:col-span-12">
              <Deferred title={ru.dash.activity} minHeight={300}>
                <ActivityTile data={dash.activity} people={dash.people} to={me.abilities.journal ? '/journal' : undefined} />
              </Deferred>
            </div>
            <div className="lg:col-span-8">
              <Deferred title={ru.dash.strip} minHeight={130}>
                <FilmStrip scenes={dash.film_strip} />
              </Deferred>
            </div>
            <div className="lg:col-span-4">
              <Deferred title={ru.dash.drum} minHeight={230}>
                <DrumCurve scenes={dash.drum} />
              </Deferred>
            </div>
            <div className="lg:col-span-5">
              <Deferred title={ru.dash.feed} minHeight={560}>
                <FeedTile items={dash.feed} hidden={!me.abilities.journal} />
              </Deferred>
            </div>
            <div className="lg:col-span-4">
              <Deferred title={ru.dash.contribution} minHeight={240}>
                <ContributionTile rows={dash.contribution} people={dash.people} />
              </Deferred>
            </div>
            <div className="lg:col-span-3">
              <Deferred title={ru.dash.myTasks} minHeight={220}>
                <MyTasksTile tasks={dash.my_tasks} />
              </Deferred>
            </div>
          </>
        )}
    </>
  )
}
