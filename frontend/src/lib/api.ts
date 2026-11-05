import { apiPath } from '@/lib/project'

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
  return fetch(`/api${apiPath(path)}`, {
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
  edit_project: boolean
}

export interface Me {
  user: User
  abilities: Abilities
}

export interface ProjectBrief {
  slug: string
  title: string
  title_en: string
  role: User['role']
  archived: boolean
}

/** Кто вошёл и какие проекты ему открыты (вне проекта). */
export interface SessionInfo {
  user: User
  is_superadmin: boolean
  projects: ProjectBrief[]
  /** Можно ли этому человеку создать свой проект (самообслуживание включено и предел не исчерпан). */
  can_create_projects: boolean
}

/** Группа Telegram, которой человек может распоряжаться: в ней есть и юзербот, и он (администратор). */
export interface AvailableChat {
  id: number
  title: string
}

export interface AvailableChats {
  ready: boolean
  userbot: { username: string | null; name: string | null } | null
  chats: AvailableChat[]
  message: string | null
}

export interface NewProjectBody {
  title: string
  title_en?: string
  deadline?: string
  chat_id: number | null
}

export interface Project {
  id: number
  slug: string
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
