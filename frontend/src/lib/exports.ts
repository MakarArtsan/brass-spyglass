import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Person } from '@/lib/types'

export type ExportTarget = 'resolve' | 'premiere'
export type ExportLevel = 'scenes' | 'shots'

export interface ExportParams {
  target: ExportTarget
  level: ExportLevel
  placeholders: boolean
  references: boolean
  media_root: string
}

export interface PreviewClip {
  name: string
  kind: 'file' | 'placeholder'
  label: string
  scene_number: number
  shot_code: string | null
  timecode: string
  frames: number
  seconds: number
  status: string
}

export interface ExportPreview {
  fps: number
  clips: PreviewClip[]
  ready: number
  placeholders: number
  total_sec: number
  audio: number
  subtitles: number
  references: number
  skipped: string[]
  bytes_needed: number
}

export interface ExportItem {
  id: number
  target: ExportTarget
  level: ExportLevel
  placeholders: boolean
  references: boolean
  media_root: string
  created_at: string
  created_by: Person | null
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  error: string | null
  result: { clips: number; placeholders: number; size_bytes: number; subtitles: number; audio: number } | null
  expires_at: string
  expired: boolean
  available: boolean
  download_url: string | null
}

export const useExportPreview = (level: ExportLevel, placeholders: boolean, references: boolean) =>
  useQuery({
    queryKey: ['exports', 'preview', level, placeholders, references] as const,
    queryFn: () => api<ExportPreview>(`/exports/preview?level=${level}&placeholders=${placeholders}&references=${references}`),
  })

export const useExports = () =>
  useQuery({
    queryKey: ['exports', 'history'] as const,
    queryFn: () => api<ExportItem[]>('/exports'),
    // Прогресс приходит по SSE; опрос — запасной путь, пока что-то собирается.
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === 'queued' || e.status === 'running') ? 3000 : false),
  })

export function useCreateExport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params: ExportParams) => api<ExportItem>('/exports', { method: 'POST', body: JSON.stringify(params) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['exports', 'history'] })
      void qc.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}
