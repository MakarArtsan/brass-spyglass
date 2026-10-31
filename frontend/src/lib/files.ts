import type { LibraryItem } from '@/lib/types'

export const hostOf = (url: string | null): string => {
  try {
    return url ? new URL(url).hostname.replace(/^www\./, '') : ''
  } catch {
    return url ?? ''
  }
}

/** Как называть файл: у ссылки — заголовок страницы или сайт, у остальных — имя файла. */
export const displayName = (file: Pick<LibraryItem, 'id' | 'kind' | 'original_name' | 'link_title' | 'url'>): string =>
  file.kind === 'link' ? (file.link_title ?? hostOf(file.url)) || `#${file.id}` : (file.original_name ?? `#${file.id}`)
