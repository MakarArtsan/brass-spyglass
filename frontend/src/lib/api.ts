export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

declare global {
  interface Window {
    /** Запросы, которые index.html запустил до загрузки скриптов (ключ — путь без /api). */
    __early?: Record<string, Promise<Response> | undefined>
  }
}

/** Ответ на ранний запрос отдаётся один раз и только для GET; дальше запросы идут как обычно. */
function takeEarly(path: string, init: RequestInit): Promise<Response> | undefined {
  const early = window.__early
  if (!early || (init.method ?? 'GET') !== 'GET') return undefined
  const hit = early[path]
  delete early[path]
  return hit
}

function send(path: string, init: RequestInit): Promise<Response> {
  return fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
  })
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const early = takeEarly(path, init)
  let res: Response
  if (early) {
    try {
      res = await early
    } catch {
      res = await send(path, init) // ранний запрос не дошёл — повторяем обычным
    }
  } else {
    res = await send(path, init)
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      // 422 от валидатора приходит списком объектов — человеку он ни о чём не говорит
      detail = typeof body.detail === 'string' ? body.detail : 'Некорректные данные'
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(res.status, detail)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

export interface User {
  id: number
  tg_username: string | null
  name: string
  color: string
  role: 'owner' | 'director' | 'team' | 'guest'
  has_avatar: boolean
  last_seen_at: string | null
}

export interface Abilities {
  upload: boolean
  export: boolean
  journal: boolean
  manage_users: boolean
  restore: boolean
}

export interface Me {
  user: User
  abilities: Abilities
}

export interface Project {
  id: number
  title: string
  title_en: string
  contest: string
  deadline_official: string
  deadline_internal: string
  fps: number
  width: number
  height: number
  target_min_sec: number
  target_max_sec: number
  storage_limit_gb: number
}

export interface AuthConfig {
  login_available: boolean
  bot_username: string
}

export interface LoginToken {
  token: string
  bot_url: string
  expires_in: number
}
