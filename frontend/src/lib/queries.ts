import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { api, type Project } from '@/lib/api'
import { dashboardKey, type DashboardData } from '@/lib/dashboard'
import type {
  ActivityPage,
  Asset,
  AssetDetail,
  Attached,
  CommentItem,
  FileItem,
  FinalFile,
  LibraryPage,
  Meta,
  Scene,
  Setup,
  Shot,
  ShotDetail,
  SoundCue,
  Task,
} from '@/lib/types'

export type Resource = 'scenes' | 'shots' | 'assets' | 'setups' | 'sound' | 'tasks'

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const keys = {
  meta: ['meta'] as const,
  list: (r: Resource) => [r] as const,
  shot: (id: number) => ['shot', id] as const,
  asset: (id: number) => ['asset', id] as const,
  files: (type: string, id: number) => ['files', type, id] as const,
  comments: (type: string, id: number) => ['comments', type, id] as const,
  activity: (filter: object) => ['activity', filter] as const,
}

/** Что ещё устаревает, когда меняется ресурс. */
const RELATED: Record<Resource, string[]> = {
  scenes: ['scenes'],
  shots: ['shots', 'scenes', 'shot', 'assets'],
  assets: ['assets', 'asset', 'shots'],
  setups: ['setups'],
  sound: ['sound', 'shot'],
  tasks: ['tasks'],
}

export function invalidateResource(qc: QueryClient, resource: Resource): Promise<unknown> {
  return Promise.all([
    ...RELATED[resource].map((k) => qc.invalidateQueries({ queryKey: [k] })),
    qc.invalidateQueries({ queryKey: ['activity'] }),
  ])
}

export const fetchers = {
  scenes: () => api<Scene[]>('/scenes'),
  shots: () => api<Shot[]>('/shots'),
  assets: () => api<Asset[]>('/assets'),
  setups: () => api<Setup[]>('/setups'),
  sound: () => api<SoundCue[]>('/sound'),
  tasks: () => api<Task[]>('/tasks'),
}

export const useMeta = () =>
  useQuery({ queryKey: keys.meta, queryFn: () => api<Meta>('/meta'), staleTime: Infinity })
export const useScenes = () => useQuery({ queryKey: keys.list('scenes'), queryFn: fetchers.scenes })
export const useShots = () => useQuery({ queryKey: keys.list('shots'), queryFn: fetchers.shots })
export const useAssets = () => useQuery({ queryKey: keys.list('assets'), queryFn: fetchers.assets })
export const useSetups = () => useQuery({ queryKey: keys.list('setups'), queryFn: fetchers.setups })
export const useSounds = () => useQuery({ queryKey: keys.list('sound'), queryFn: fetchers.sound })
export const useTasks = () => useQuery({ queryKey: keys.list('tasks'), queryFn: fetchers.tasks })

export const useShot = (id: number | null) =>
  useQuery({
    queryKey: keys.shot(id ?? 0),
    queryFn: () => api<ShotDetail>(`/shots/${id}`),
    enabled: id != null,
  })

export const useAsset = (id: number | null) =>
  useQuery({
    queryKey: keys.asset(id ?? 0),
    queryFn: () => api<AssetDetail>(`/assets/${id}`),
    enabled: id != null,
  })

/** Файлы карточки. Пока что-то обрабатывается (превью, прокси), опрашиваем раз в 1,5 с. */
export function useEntityFiles(type: string, id: number | null) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: keys.files(type, id ?? 0),
    queryFn: () => api<Attached[]>(`/files?entity_type=${type}&entity_id=${id}`),
    enabled: id != null,
    refetchInterval: (q) => (q.state.data?.some((a) => a.file.processing) ? 1500 : false),
  })
  const processing = query.data?.some((a) => a.file.processing) ?? false
  const was = useRef(false)
  useEffect(() => {
    if (was.current && !processing) {
      // превью готово — обновим списки, где оно показывается
      for (const k of ['shots', 'assets', 'scenes', 'shot', 'asset']) qc.invalidateQueries({ queryKey: [k] })
    }
    was.current = processing
  }, [processing, qc])
  return query
}

export const useComments = (type: string, id: number | null) =>
  useQuery({
    queryKey: keys.comments(type, id ?? 0),
    queryFn: () => api<CommentItem[]>(`/comments?entity_type=${type}&entity_id=${id}`),
    enabled: id != null,
  })

export interface ActivityFilter {
  entity_type?: string
  entity_id?: number
  actor_id?: number
}

export function useActivity(filter: ActivityFilter, enabled = true) {
  return useInfiniteQuery({
    queryKey: keys.activity(filter),
    enabled,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: '40' })
      if (pageParam != null) params.set('before_id', String(pageParam))
      for (const [k, v] of Object.entries(filter)) if (v != null) params.set(k, String(v))
      return api<ActivityPage>(`/activity?${params}`)
    },
    getNextPageParam: (last) => last.next_before_id,
  })
}

// --- изменения -----------------------------------------------------------------------------------

type Item = { id: number }

/** Правка полей: интерфейс обновляется сразу (смена статуса видна мгновенно), при ошибке откат. */
export function useUpdate<T extends Item>(resource: Resource) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Record<string, unknown> }) =>
      api<T>(`/${resource}/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: [resource] })
      const previous = qc.getQueryData<T[]>([resource])
      qc.setQueryData<T[]>([resource], (list) => list?.map((i) => (i.id === id ? { ...i, ...patch } : i)))
      return { previous }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData([resource], ctx.previous)
    },
    onSuccess: (server, { id }) => {
      qc.setQueryData<T[]>([resource], (list) => list?.map((i) => (i.id === id ? { ...i, ...server } : i)))
    },
    onSettled: () => invalidateResource(qc, resource),
  })
}

export function useCreate<T extends Item>(resource: Resource) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<T>(`/${resource}`, json(body)),
    onSuccess: () => invalidateResource(qc, resource),
  })
}

export function useDelete(resource: Resource) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/${resource}/${id}`, { method: 'DELETE' }),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: [resource] })
      const previous = qc.getQueryData<Item[]>([resource])
      qc.setQueryData<Item[]>([resource], (list) => list?.filter((i) => i.id !== id))
      return { previous }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData([resource], ctx.previous)
    },
    onSuccess: (_data, id) => {
      // карточка удалённого больше не существует: не перечитываем её (иначе 404 и три повтора с паузами)
      const detail = DETAIL_KEY[resource]
      if (detail) qc.removeQueries({ queryKey: [detail, id] })
    },
    // Без `return`: мутация не должна ждать перечитывания списков, иначе «готово» приходит с задержкой.
    onSettled: () => void invalidateResource(qc, resource),
  })
}

/** Ключ запроса карточки у тех ресурсов, где она грузится отдельно. */
const DETAIL_KEY: Partial<Record<Resource, string>> = { shots: 'shot', assets: 'asset' }

const ENTITY_RESOURCE = { scene: 'scenes', shot: 'shots', asset: 'assets', setup_payoff: 'setups', sound_cue: 'sound', task: 'tasks' } as const

/** Групповая смена статуса выбранных строк. */
export function useBulkStatus(entity: keyof typeof ENTITY_RESOURCE) {
  const qc = useQueryClient()
  const resource = ENTITY_RESOURCE[entity]
  return useMutation({
    mutationFn: ({ ids, status }: { ids: number[]; status: string }) =>
      api<{ updated: number }>('/bulk-status', json({ entity_type: entity, ids, status })),
    onMutate: async ({ ids, status }) => {
      await qc.cancelQueries({ queryKey: [resource] })
      const previous = qc.getQueryData<Item[]>([resource])
      const set = new Set(ids)
      qc.setQueryData<Item[]>([resource], (list) => list?.map((i) => (set.has(i.id) ? { ...i, status } : i)))
      return { previous }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData([resource], ctx.previous)
    },
    onSettled: () => invalidateResource(qc, resource),
  })
}

/** Перестановка порядка перетаскиванием: список в кэше переставляется сразу. */
export function useReorder(entity: 'scene' | 'shot') {
  const qc = useQueryClient()
  const resource = entity === 'scene' ? 'scenes' : 'shots'
  return useMutation({
    mutationFn: ({ ids, sceneId }: { ids: number[]; sceneId?: number }) =>
      api<{ moved: number }>('/reorder', json({ entity_type: entity, ids, scene_id: sceneId ?? null })),
    onMutate: async ({ ids }) => {
      await qc.cancelQueries({ queryKey: [resource] })
      const previous = qc.getQueryData<(Item & { order: number })[]>([resource])
      const position = new Map(ids.map((id, i) => [id, i + 1]))
      qc.setQueryData<(Item & { order: number })[]>([resource], (list) =>
        list?.map((i) => (position.has(i.id) ? { ...i, order: position.get(i.id)! } : i)),
      )
      return { previous }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData([resource], ctx.previous)
    },
    onSettled: () => invalidateResource(qc, resource),
  })
}

export function useShotAsset(shotId: number) {
  const qc = useQueryClient()
  const refresh = () => {
    for (const k of ['shots', 'shot', 'assets', 'asset', 'activity']) qc.invalidateQueries({ queryKey: [k] })
  }
  return {
    set: useMutation({
      mutationFn: ({ assetId, stateId }: { assetId: number; stateId: number | null }) =>
        api(`/shots/${shotId}/assets/${assetId}`, { method: 'PUT', body: JSON.stringify({ asset_state_id: stateId }) }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (assetId: number) => api(`/shots/${shotId}/assets/${assetId}`, { method: 'DELETE' }),
      onSuccess: refresh,
    }),
  }
}

export function useAssetStates(assetId: number) {
  const qc = useQueryClient()
  const refresh = () => {
    for (const k of ['assets', 'asset', 'shot', 'shots']) qc.invalidateQueries({ queryKey: [k] })
  }
  return {
    create: useMutation({
      mutationFn: (name: string) => api(`/assets/${assetId}/states`, json({ name })),
      onSuccess: refresh,
    }),
    rename: useMutation({
      mutationFn: ({ id, name }: { id: number; name: string }) =>
        api(`/asset-states/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api(`/asset-states/${id}`, { method: 'DELETE' }),
      onSuccess: refresh,
    }),
  }
}

export function useCommentMutations(type: string, id: number) {
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.comments(type, id) })
    qc.invalidateQueries({ queryKey: ['activity'] })
  }
  return {
    add: useMutation({
      mutationFn: (body: string) => api('/comments', json({ entity_type: type, entity_id: id, body })),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (commentId: number) => api(`/comments/${commentId}`, { method: 'DELETE' }),
      onSuccess: refresh,
    }),
  }
}

export function useFileVersions(fileId: number | null) {
  return useQuery({
    queryKey: ['file-versions', fileId] as const,
    queryFn: () => api<FileItem[]>(`/files/${fileId}/versions`),
    enabled: fileId != null,
  })
}

/** Откат: выбранная версия становится текущей на всех карточках, где лежит файл. */
export function useRollback() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: number) => api<FileItem>(`/files/${fileId}/rollback`, { method: 'POST' }),
    onSuccess: () => {
      for (const k of ['file-versions', 'files', 'library', 'shots', 'scenes', 'shot', 'activity']) {
        qc.invalidateQueries({ queryKey: [k] })
      }
    },
  })
}

/** Финальный файл сцены или шота (null — снять выбор). */
export function useSetFinal(type: 'scene' | 'shot', id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: number | null) =>
      api<{ final: FinalFile | null }>(`/${type}s/${id}/final`, { method: 'PUT', body: JSON.stringify({ file_id: fileId }) }),
    onSuccess: () => {
      for (const k of [type === 'scene' ? 'scenes' : 'shots', 'shot', 'activity', 'dashboard', 'animatic']) {
        qc.invalidateQueries({ queryKey: [k] })
      }
    },
  })
}

export function useFileMutations(type: string, id: number) {
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.files(type, id) })
    for (const k of ['shots', 'assets', 'scenes', 'shot', 'asset', 'activity']) qc.invalidateQueries({ queryKey: [k] })
  }
  return {
    detach: useMutation({
      mutationFn: (attachmentId: number) => api(`/attachments/${attachmentId}`, { method: 'DELETE' }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (fileId: number) => api(`/files/${fileId}`, { method: 'DELETE' }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ fileId, patch }: { fileId: number; patch: Record<string, unknown> }) =>
        api(`/files/${fileId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
      onSuccess: refresh,
    }),
  }
}

/**
 * Ускоряет первый показ: пока React поднимается, уже летят данные и код нужной страницы.
 * Без этого цепочка «скрипт → /api/me → код страницы → данные» на 4G даёт 3+ секунды.
 */
export function warmUpRoute(qc: QueryClient, path: string): void {
  if (path.startsWith('/login')) return
  const prefetch = (key: readonly unknown[], fn: () => Promise<unknown>) => void qc.prefetchQuery({ queryKey: key, queryFn: fn, staleTime: 60_000 })
  const meta = () => prefetch(keys.meta, () => api<Meta>('/meta'))
  if (path.startsWith('/shots')) {
    void import('@/pages/Shots')
    prefetch(keys.list('shots'), fetchers.shots)
    prefetch(keys.list('scenes'), fetchers.scenes)
    meta()
  } else if (path.startsWith('/scenes')) {
    void import('@/pages/Scenes')
    prefetch(keys.list('scenes'), fetchers.scenes)
  } else if (path.startsWith('/assets')) {
    void import('@/pages/Assets')
    prefetch(keys.list('assets'), fetchers.assets)
    meta()
  } else if (path === '/') {
    void import('@/pages/DashboardTiles')
    prefetch(['project'], () => api<Project>('/project'))
    prefetch(dashboardKey, () => api<DashboardData>('/dashboard'))
  } else if (path.startsWith('/tasks')) {
    void import('@/pages/Tasks')
    prefetch(keys.list('tasks'), fetchers.tasks)
    meta()
  }
}

// --- медиатека и ссылки --------------------------------------------------------------------------

export interface LibraryFilter {
  kind?: string
  source?: string
  author?: number
  since?: string
  until?: string
  unattached?: boolean
  q?: string
}

const libraryQuery = (filter: LibraryFilter, before: number | null): string => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filter)) {
    if (value !== undefined && value !== '' && value !== false) params.set(key, String(value))
  }
  if (before !== null) params.set('before_id', String(before))
  return params.toString()
}

/** Все файлы проекта новыми сверху, постранично. */
export function useLibrary(filter: LibraryFilter) {
  return useInfiniteQuery({
    queryKey: ['library', filter] as const,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => api<LibraryPage>(`/library?${libraryQuery(filter, pageParam)}`),
    getNextPageParam: (last) => last.next_before_id,
    // Пока файл обрабатывается (превью, заголовок ссылки), список перечитывается сам.
    refetchInterval: (query) => (query.state.data?.pages.some((p) => p.items.some((i) => i.processing)) ? 2000 : false),
  })
}

interface LinkTarget {
  entityType: string
  entityId: number
  purpose: string
}

/** Ссылка как файл; можно сразу привязать к карточке. */
export function useAddLink(target?: LinkTarget) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (url: string) =>
      api<{ file: FileItem; created: boolean }>('/links', {
        method: 'POST',
        body: JSON.stringify({ url, ...(target ? { entity_type: target.entityType, entity_id: target.entityId, purpose: target.purpose } : {}) }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['library'] })
      if (target) void qc.invalidateQueries({ queryKey: keys.files(target.entityType, target.entityId) })
      void qc.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

/** Привязка файлов из медиатеки к карточке без повторной загрузки. */
export function useAttachFromLibrary(entityType: string, entityId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ fileIds, purpose }: { fileIds: number[]; purpose: string }) => {
      for (const fileId of fileIds) {
        await api('/attachments', { method: 'POST', body: JSON.stringify({ file_id: fileId, entity_type: entityType, entity_id: entityId, purpose }) })
      }
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.files(entityType, entityId) })
      void qc.invalidateQueries({ queryKey: ['library'] })
      for (const k of ['shots', 'assets', 'scenes', 'shot', 'asset', 'activity']) void qc.invalidateQueries({ queryKey: [k] })
    },
  })
}
