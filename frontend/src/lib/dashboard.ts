import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** Ответ `/api/dashboard`. Все числа считает сервер (metrics.py), клиент только рисует. */

export interface Progress {
  done: number
  total: number
  pct: number
}

export interface DashPerson {
  id: number
  name: string
  color: string
  has_avatar: boolean
}

export interface DashFeedItem {
  id: number
  at: string
  action: string
  entity_type: string
  entity_id: number | null
  label: string | null
  actor: DashPerson | null
  diff: Record<string, [unknown, unknown]> | null
  thumb_url: string | null
  file_kind: string | null
}

export interface DashboardData {
  today: string
  readiness: {
    ready_sec: number
    shots_sec: number
    plan_sec: number
    pct: number
    shots: Progress
    assets: Progress
    tasks: Progress
  }
  runtime: { shots_sec: number; plan_sec: number; min_sec: number; max_sec: number; in_zone: boolean }
  seedance: { seedance_sec: number; total_sec: number; pct: number; target_pct: number }
  media: {
    total: number
    by_kind: Record<'video' | 'image' | 'audio' | 'document' | 'link', number>
    from_telegram: number
    storage: { used_bytes: number; limit_bytes: number; used_pct: number; warn: boolean; full: boolean }
  }
  activity: {
    heatmap: { d: string; n: number }[]
    bars: { d: string; uploads: number; statuses: number; comments: number; by_user: Record<string, number> }[]
  }
  burndown: {
    points: { d: string; ideal: number; actual: number | null }[]
    total_sec: number
    remaining_sec: number
    pace_sec_per_day: number
    forecast: string | null
    deadline: string
    finishes_in_time: boolean | null
  }
  contribution: { user_id: number; uploads: number; closed: number }[]
  film_strip: { scene_id: number; number: number; title: string; planned_sec: number; ready_pct: number; status: string }[]
  alerts: {
    overdue: { total: number; by_type: Record<string, number> }
    long_shots: { id: number; code: string; duration_sec: number }[]
    orphan_assets: { id: number; code: string; name: string }[]
    scenes_without_final: { id: number; number: number; title: string }[]
  }
  drum: { scene_id: number; number: number; title: string; level: number | null }[]
  my_tasks: { id: number; code: string; title: string; status: string; due_date: string | null; overdue: boolean }[]
  feed: DashFeedItem[]
  people: Record<string, DashPerson>
}

export const dashboardKey = ['dashboard'] as const

export function useDashboard() {
  // Свежесть 10 с: прогретый при загрузке ответ не перезапрашивается сразу; живые события SSE перечитывают в любом случае.
  return useQuery({ queryKey: dashboardKey, queryFn: () => api<DashboardData>('/dashboard'), staleTime: 10_000 })
}
