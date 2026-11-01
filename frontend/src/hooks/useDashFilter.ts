import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ru } from '@/ru'

const KEYS = ['status', 'long', 'tool', 'orphans', 'nofinal', 'overdue', 'mine'] as const

export interface DashFilter {
  /** Слаги статусов через запятую в адресе (`?status=done`); null — фильтра нет. */
  status: string[] | null
  long: boolean
  tool: string | null
  orphans: boolean
  nofinal: boolean
  overdue: boolean
  mine: boolean
  active: boolean
  /** Подписи действующих фильтров для баннера. */
  labels: string[]
  /** Стабильный ключ для зависимостей `useMemo`. */
  key: string
  clear: () => void
}

/**
 * Фильтры, с которыми пользователь пришёл с плитки дашборда («Просрочено» → `/tasks?overdue=1`).
 * Читаются из адреса, поэтому ссылкой можно поделиться, а переход по другой плитке меняет фильтр сразу.
 */
export function useDashFilter(): DashFilter {
  const [params, setParams] = useSearchParams()
  const status = params.get('status')?.split(',').filter(Boolean) ?? null
  const tool = params.get('tool')
  const flags = { long: params.has('long'), orphans: params.has('orphans'), nofinal: params.has('nofinal'), overdue: params.has('overdue'), mine: params.has('mine') }
  const labels = [
    status?.includes('done') && status.length === 1 ? ru.dash.filterDone : null,
    flags.long ? ru.dash.filterLong : null,
    tool === 'seedance' ? ru.dash.filterSeedance : tool,
    flags.orphans ? ru.dash.filterOrphans : null,
    flags.nofinal ? ru.dash.filterNoFinal : null,
    flags.overdue ? ru.dash.filterOverdue : null,
    flags.mine ? ru.dash.filterMine : null,
  ].filter((label): label is string => Boolean(label))
  const clear = useCallback(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        KEYS.forEach((key) => next.delete(key))
        return next
      },
      { replace: true },
    )
  }, [setParams])
  return {
    status,
    tool,
    ...flags,
    active: KEYS.some((key) => params.has(key)),
    labels,
    key: KEYS.map((key) => params.get(key) ?? '').join('|'),
    clear,
  }
}
