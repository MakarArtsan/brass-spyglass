import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { FinalFile } from '@/lib/types'

export interface AnimaticShot {
  id: number
  code: string
  description: string | null
  status: string
  side: 'north' | 'south' | null
  duration_sec: number
  start_sec: number
  end_sec: number
  final: FinalFile | null
}

export interface AnimaticScene {
  id: number
  number: number
  title: string
  status: string
  planned_sec: number
  start_sec: number
  end_sec: number
  final: FinalFile | null
  shots: AnimaticShot[]
}

export interface SoundBlock {
  id: number
  code: string
  type: string
  lane: 1 | 2 | 3
  who: string | null
  text_en: string | null
  start_sec: number
  end_sec: number
  has_file: boolean
  shot_id: number | null
  scene_id: number | null
}

/** Что играет в «Смотреть фильм»: готовый файл или карточка с описанием на время шота. */
export interface Segment {
  kind: 'file' | 'card'
  scene_id: number
  shot_id: number | null
  title: string
  description: string | null
  start_sec: number
  end_sec: number
  duration_sec: number
  file: FinalFile | null
}

export interface Animatic {
  total_sec: number
  scenes: AnimaticScene[]
  sound: SoundBlock[]
  playlist: Segment[]
  ready_count: number
}

export const useAnimatic = () => useQuery({ queryKey: ['animatic'], queryFn: () => api<Animatic>('/animatic') })
