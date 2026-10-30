import { useQuery } from '@tanstack/react-query'
import { Loader2, Send } from 'lucide-react'
import { Navigate } from 'react-router-dom'
import { ContestBadge } from '@/components/ContestBadge'
import { Logo } from '@/components/Logo'
import { StraitMap } from '@/components/StraitMap'
import { TelegramWidget } from '@/components/TelegramWidget'
import { Button } from '@/components/ui/button'
import { FILM } from '@/brand'
import { useMe } from '@/hooks/useAuth'
import { useTelegramLogin } from '@/hooks/useTelegramLogin'
import { api, type AuthConfig } from '@/lib/api'
import { ru } from '@/ru'

const errorText = {
  expired: ru.login.expired,
  unavailable: ru.login.unavailable,
  failed: ru.login.failed,
  not_member: ru.login.notMember,
} as const

export default function Login() {
  const me = useMe()
  const config = useQuery({ queryKey: ['auth-config'], queryFn: () => api<AuthConfig>('/auth/config') })
  const { state, start, cancel, widget } = useTelegramLogin()

  if (me.data) return <Navigate to="/" replace />

  const unavailable = config.data && !config.data.login_available
  const busy = state.phase === 'opening'

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-4 py-10">
      <StraitMap variant="page" className="absolute inset-0 h-full w-full opacity-90" />
      <div className="absolute inset-0 bg-gradient-to-b from-ink/60 via-ink/30 to-ink" aria-hidden />

      <main className="panel relative w-full max-w-md p-6 shadow-2xl shadow-black/40 sm:p-8">
        <Logo className="mb-6" withTeam />
        <h1 className="font-display text-4xl leading-none">{ru.login.title}</h1>
        <p className="mt-1 font-display text-lg text-brass">{FILM.title}</p>
        <p className="mt-4 text-sm text-fog">{ru.login.lead}</p>

        {state.phase === 'waiting' ? (
          <div className="mt-6 space-y-4" role="status">
            <div className="flex items-center gap-3 text-sm">
              <Loader2 className="animate-spin text-brass" size={20} />
              <span className="font-semibold">{ru.login.waiting}</span>
            </div>
            <p className="text-sm text-fog">{ru.login.waitingHint}</p>
            <div className="flex gap-3">
              <Button asChild size="lg" className="flex-1">
                <a href={state.botUrl} target="_blank" rel="noreferrer">
                  <Send size={18} />
                  {ru.login.openBot}
                </a>
              </Button>
              <Button variant="outline" size="lg" onClick={cancel}>
                {ru.login.cancel}
              </Button>
            </div>
          </div>
        ) : (
          <Button size="lg" className="mt-6 w-full" onClick={start} disabled={busy || !!unavailable}>
            {busy ? <Loader2 className="animate-spin" size={18} /> : <Send size={18} />}
            {busy ? ru.login.opening : ru.login.button}
          </Button>
        )}

        {unavailable && state.phase !== 'error' && (
          <p role="alert" className="mt-4 text-sm text-alert">
            {ru.login.unavailable}
          </p>
        )}
        {state.phase === 'error' && (
          <p role="alert" className="mt-4 text-sm text-alert">
            {errorText[state.reason]}
          </p>
        )}

        {config.data?.login_available && config.data.bot_username && (
          <details className="mt-6 border-t border-line pt-4 text-sm text-fog">
            <summary className="flex min-h-touch cursor-pointer items-center">{ru.login.widgetSummary}</summary>
            <p className="mb-3">{ru.login.widgetHint}</p>
            <TelegramWidget bot={config.data.bot_username} onAuth={widget} />
          </details>
        )}
      </main>

      <ContestBadge className="relative mt-6" />
    </div>
  )
}
