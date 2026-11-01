import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Person } from '@/lib/types'

export interface NotificationItem {
  id: number
  kind: 'comment' | 'file' | 'version'
  count: number
  snippet: string | null
  actor: Person | null
  entity_type: string
  entity_id: number
  label: string | null
  /** Куда вести клик: карточка шота, сцены, ассета или страница раздела. */
  url: string
  created_at: string
  read: boolean
}

export interface Inbox {
  unread: number
  items: NotificationItem[]
}

const KEY = ['notifications'] as const

/** Число непрочитанного живёт на SSE-обновлениях: событие в проекте → перечитать входящие. */
export const useNotifications = () =>
  useQuery({ queryKey: KEY, queryFn: () => api<Inbox>('/notifications'), staleTime: 15_000, refetchOnWindowFocus: true })

export function useReadNotification() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<{ unread: number }>(`/notifications/${id}/read`, { method: 'POST' }),
    onMutate: (id) => {
      // прочитанное гаснет сразу, не дожидаясь ответа
      qc.setQueryData<Inbox>(KEY, (old) =>
        old
          ? {
              unread: Math.max(0, old.unread - (old.items.find((i) => i.id === id && !i.read) ? 1 : 0)),
              items: old.items.map((i) => (i.id === id ? { ...i, read: true } : i)),
            }
          : old,
      )
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useReadAll() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ unread: number }>('/notifications/read-all', { method: 'POST' }),
    onMutate: () => {
      qc.setQueryData<Inbox>(KEY, (old) => (old ? { unread: 0, items: old.items.map((i) => ({ ...i, read: true })) } : old))
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: KEY }),
  })
}
