/**
 * Проект, в котором открыт сайт. Адрес страницы — `/p/<slug>/…`; все запросы проекта идут на
 * `/api/p/<slug>/…`. Сменить проект — значит открыть другой адрес: страница загружается заново, и
 * ничего от прежнего проекта (кэш запросов, подписки) в новом не остаётся.
 */

const PATH = /^\/p\/([^/]+)(\/.*)?$/
const LAST_KEY = 'last-project'

export function slugOf(pathname: string): string | null {
  const match = PATH.exec(pathname)
  return match ? decodeURIComponent(match[1]) : null
}

/** Адрес страницы без префикса проекта: `/p/film/shots` → `/shots`. */
export function innerPath(pathname: string): string {
  const match = PATH.exec(pathname)
  return match ? (match[2] ?? '/') : pathname
}

/** Проект этой загрузки страницы (null — мы вне проектов: вход, выбор проекта). */
export const currentSlug: string | null = slugOf(location.pathname)

// Вне проектов: кто вошёл, список проектов, вход, аватары.
const GLOBAL = ['/projects', '/session', '/auth/', '/health', '/users/']

export const isGlobal = (path: string): boolean => GLOBAL.some((g) => path === g || path.startsWith(g))

/** Путь запроса с префиксом проекта: `/shots` → `/p/film/shots` (общие пути не меняются). */
export function apiPath(path: string): string {
  if (isGlobal(path)) return path
  if (!currentSlug) throw new Error(`Запрос ${path} вне проекта`)
  return `/p/${encodeURIComponent(currentSlug)}${path}`
}

/** Полный адрес для ссылок и загрузок (`<a href>`, XHR): `/api/p/film/subtitles.srt`. */
export const apiHref = (path: string): string => `/api${apiPath(path)}`

export function rememberProject(slug: string): void {
  try {
    localStorage.setItem(LAST_KEY, slug)
  } catch {
    /* хранилище недоступно — проект просто не запомнится */
  }
}

export function lastProject(): string | null {
  try {
    return localStorage.getItem(LAST_KEY)
  } catch {
    return null
  }
}

export function openProject(slug: string, inner = '/'): void {
  rememberProject(slug)
  window.location.assign(`/p/${encodeURIComponent(slug)}${inner}`)
}
