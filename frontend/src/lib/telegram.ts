import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** Окно «Добавить из Telegram»: индекс чата, импорт выбранного и прогресс. */

export interface TgTopic {
  topic_id: number
  title: string
  icon_emoji: string | null
  media_count: number
  last_synced_at: string | null
  history_complete: boolean
  latest_thumb_url: string | null
}

export interface TgMediaItem {
  id: number
  message_id: number
  topic_id: number
  kind: 'image' | 'video' | 'audio' | 'document' | 'link'
  mime: string | null
  caption: string | null
  file_name: string | null
  url: string | null
  grouped_id: number | null
  author_name: string | null
  posted_at: string
  size_bytes: number | null
  duration_sec: number | null
  thumb_url: string | null
  imported_file_id: number | null
  open_url: string | null
}

export interface TgMediaPage {
  items: TgMediaItem[]
  next_before_id: number | null
}

export interface TgStatus {
  configured: boolean
  connected: boolean
  chat_id: number | null
  syncing: boolean
  phase: string
  topic: string | null
  thumbs_left: number
  last_error: string | null
  last_run_at: string | null
  overview: { topics: number; media: number; topics_complete: number; last_synced_at: string | null } | null
}

export interface TgJob {
  id: number
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  error: string | null
  total: number
  entity_type: string | null
  entity_id: number | null
}

export interface TgFilter {
  topicId: number | null
  kinds: string[]
  q: string
  hideImported: boolean
}

export const tgKeys = {
  status: ['tg', 'status'] as const,
  topics: ['tg', 'topics'] as const,
  jobs: ['tg', 'jobs'] as const,
}

export const useTgStatus = () =>
  useQuery({
    queryKey: tgKeys.status,
    queryFn: () => api<TgStatus>('/tg/status'),
    refetchInterval: (q) => (q.state.data?.syncing ? 3000 : false),
  })

export const useTgTopics = () => useQuery({ queryKey: tgKeys.topics, queryFn: () => api<TgTopic[]>('/tg/topics') })

const mediaQuery = (filter: TgFilter, before: number | null): string => {
  const params = new URLSearchParams()
  if (filter.topicId !== null) params.set('topic_id', String(filter.topicId))
  if (filter.kinds.length > 0) params.set('kinds', filter.kinds.join(','))
  if (filter.q.trim() !== '') params.set('q', filter.q.trim())
  if (filter.hideImported) params.set('hide_imported', 'true')
  if (before !== null) params.set('before_id', String(before))
  return params.toString()
}

/** Медиа темы, новые сверху, постранично (бесконечная прокрутка). */
export const useTgMedia = (filter: TgFilter) =>
  useInfiniteQuery({
    queryKey: ['tg', 'media', filter] as const,
    enabled: filter.topicId !== null,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => api<TgMediaPage>(`/tg/media?${mediaQuery(filter, pageParam)}`),
    getNextPageParam: (last) => last.next_before_id,
  })

/** Импорт идёт фоновой задачей: прогресс виден в углу экрана, окно можно закрыть. */
export function useTgImport(entityType: string, entityId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ mediaIds, purpose }: { mediaIds: number[]; purpose: string }) =>
      api<{ job_id: number; count: number }>('/tg/import', {
        method: 'POST',
        body: JSON.stringify({ media_ids: mediaIds, entity_type: entityType, entity_id: entityId, purpose }),
      }),
    onSuccess: () => {
      tgJobsHint.raise()
      void qc.invalidateQueries({ queryKey: tgKeys.jobs })
    },
  })
}

export interface TgViewState {
  ready: boolean
  url: string | null
  job_id: number | null
}

/** Файл для просмотра в окне: пока не скачан, опрашиваем, пока сервер не скажет «готов». */
export const useTgView = (mediaId: number | null) =>
  useQuery({
    queryKey: ['tg', 'view', mediaId] as const,
    enabled: mediaId !== null,
    queryFn: () => api<TgViewState>(`/tg/media/${mediaId}/view`, { method: 'POST' }),
    refetchInterval: (q) => (q.state.data && !q.state.data.ready ? 1200 : false),
    staleTime: 20 * 60 * 1000, // ссылка подписана на час: до этого перезапрашивать незачем
    gcTime: 0,
  })

/**
 * Запрос «моих импортов» не нужен, пока ничего не импортируется: без него каждая страница делала бы лишний
 * запрос на старте. Включается, когда импорт начат здесь или пришло событие задачи по SSE.
 */
const hint = { raised: false, listeners: new Set<() => void>() }
export const tgJobsHint = {
  subscribe: (listener: () => void) => {
    hint.listeners.add(listener)
    return () => hint.listeners.delete(listener)
  },
  get: () => hint.raised,
  raise: () => {
    if (hint.raised) return
    hint.raised = true
    hint.listeners.forEach((l) => l())
  },
}

export const useTgJobs = (enabled = true) =>
  useQuery({
    queryKey: tgKeys.jobs,
    enabled,
    queryFn: () => api<TgJob[]>('/tg/jobs'),
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === 'queued' || j.status === 'running') ? 2000 : false),
  })

export function useTgSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api('/tg/sync', { method: 'POST' }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: tgKeys.status }),
  })
}
