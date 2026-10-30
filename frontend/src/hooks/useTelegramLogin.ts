import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { meKey } from '@/hooks/useAuth'
import { api, ApiError, type LoginToken, type User } from '@/lib/api'

export type LoginState =
  | { phase: 'idle' }
  | { phase: 'opening' }
  | { phase: 'waiting'; botUrl: string }
  | { phase: 'error'; reason: 'expired' | 'unavailable' | 'failed' | 'not_member' }

/**
 * Вход через бота: сайт получает одноразовый токен, открывает t.me/<бот>?start=<токен>
 * и ждёт подтверждения по SSE. Подтвердили — забирает сессию (httpOnly-cookie).
 */
export function useTelegramLogin() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [state, setState] = useState<LoginState>({ phase: 'idle' })
  const source = useRef<EventSource | null>(null)

  const stop = useCallback(() => {
    source.current?.close()
    source.current = null
  }, [])
  useEffect(() => stop, [stop])

  const finish = useCallback(async () => {
    await qc.invalidateQueries({ queryKey: meKey })
    navigate('/', { replace: true })
  }, [qc, navigate])

  const start = useCallback(async () => {
    stop()
    setState({ phase: 'opening' })
    // Окно открываем сразу по клику, иначе Safari и мобильные браузеры блокируют всплывающее окно.
    const popup = window.open('about:blank', '_blank')
    if (popup) popup.opener = null
    try {
      const login = await api<LoginToken>('/auth/login-token', { method: 'POST' })
      if (popup) popup.location.href = login.bot_url
      setState({ phase: 'waiting', botUrl: login.bot_url })

      const es = new EventSource(`/api/auth/login-token/${login.token}/events`)
      source.current = es
      es.addEventListener('confirmed', async () => {
        stop()
        try {
          await api<User>(`/auth/login-token/${login.token}/claim`, { method: 'POST' })
          await finish()
        } catch {
          setState({ phase: 'error', reason: 'failed' })
        }
      })
      es.addEventListener('expired', () => {
        stop()
        setState({ phase: 'error', reason: 'expired' })
      })
      es.onerror = () => {
        // CLOSED — сервер ответил ошибкой (токен забыт); CONNECTING — браузер переподключается сам.
        if (es.readyState === EventSource.CLOSED) {
          stop()
          setState({ phase: 'error', reason: 'expired' })
        }
      }
    } catch (err) {
      popup?.close()
      setState({
        phase: 'error',
        reason: err instanceof ApiError && err.status === 503 ? 'unavailable' : 'failed',
      })
    }
  }, [stop, finish])

  const cancel = useCallback(() => {
    stop()
    setState({ phase: 'idle' })
  }, [stop])

  /** Запасной путь: Telegram Login Widget передаёт подписанные данные. */
  const widget = useCallback(
    async (data: Record<string, unknown>) => {
      try {
        await api<User>('/auth/widget', { method: 'POST', body: JSON.stringify(data) })
        await finish()
      } catch (err) {
        setState({
          phase: 'error',
          reason: err instanceof ApiError && err.status === 403 ? 'not_member' : 'failed',
        })
      }
    },
    [finish],
  )

  return { state, start, cancel, widget }
}
