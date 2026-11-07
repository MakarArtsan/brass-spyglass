import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Person } from '@/lib/types'

/** Сколько фото можно собрать в один коллаж (то же число проверяет сервер). */
export const MIN_PHOTOS = 2
export const MAX_PHOTOS = 10
export const MAX_TITLE = 120

export interface CollagePhoto {
  id: number
  original_name: string | null
  size_bytes: number | null
  width: number | null
  height: number | null
  urls: { original: string; thumb?: string; preview?: string }
}

export interface Collage {
  id: number
  title: string
  width: number
  height: number
  photos: number
  size_bytes: number | null
  created_at: string
  created_by: Person | null
  /** Ссылки на картинку: превью появляется, когда сервер её обработал, до этого — оригинал. */
  urls: { original: string; thumb?: string; preview?: string }
  download_url: string
  zip_url: string
}

export interface CollageDetail extends Collage {
  photo_list: CollagePhoto[]
}

export const useCollages = () =>
  useQuery({ queryKey: ['collages'] as const, queryFn: () => api<Collage[]>('/collages') })

export const useCollage = (id: number | null) =>
  useQuery({
    queryKey: ['collages', id] as const,
    queryFn: () => api<CollageDetail>(`/collages/${id}`),
    enabled: id !== null,
  })

export function useCreateCollage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { title: string; file_ids: number[] }) =>
      api<Collage>('/collages', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => {
      // Новый коллаж — это ещё и новые файлы проекта (фото и картинка) и запись в журнале.
      for (const key of ['collages', 'files', 'library', 'activity', 'dashboard']) {
        void qc.invalidateQueries({ queryKey: [key] })
      }
    },
  })
}

export function useDeleteCollage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/collages/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['collages'] })
      void qc.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}
