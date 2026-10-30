export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
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
