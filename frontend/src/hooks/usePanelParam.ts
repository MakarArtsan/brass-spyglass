import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** Какая карточка открыта, хранится в адресе (`?shot=12`): ссылку можно отправить коллеге. */
export function usePanelParam(name: string): [number | null, (id: number | null) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get(name)
  const id = raw && /^\d+$/.test(raw) ? Number(raw) : null
  const set = useCallback(
    (next: number | null) => {
      setParams(
        (prev) => {
          const copy = new URLSearchParams(prev)
          if (next == null) copy.delete(name)
          else copy.set(name, String(next))
          return copy
        },
        { replace: next == null },
      )
    },
    [name, setParams],
  )
  return [id, set]
}
