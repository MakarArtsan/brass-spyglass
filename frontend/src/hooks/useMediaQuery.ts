import { useSyncExternalStore } from 'react'
import { breakpoints } from '@/brand'

function subscribe(query: string, cb: () => void) {
  const mq = window.matchMedia(query)
  mq.addEventListener('change', cb)
  return () => mq.removeEventListener('change', cb)
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => subscribe(query, cb),
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** ПК-раскладка — от 1024 px, всё остальное — раскладка смартфона. */
export const useIsDesktop = () => useMediaQuery(`(min-width: ${breakpoints.desktop}px)`)
