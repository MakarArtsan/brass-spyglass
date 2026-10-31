export type StatusKey = 'not_started' | 'in_progress' | 'review' | 'rework' | 'done' | 'cut'

export interface Preview {
  file_id: number
  kind: string
  url: string
}

interface Work {
  status: StatusKey
  priority: 'high' | 'medium' | 'low' | null
  assignee_id: number | null
  due_date: string | null
  comment: string | null
  created_by: number | null
  updated_by: number | null
  created_at: string
  updated_at: string
}

export interface Scene extends Work {
  id: number
  project_id: number
  number: number
  order: number
  title: string
  location: string | null
  time_of_day: string | null
  planned_sec: number
  drum_level: number | null
  meaning: string | null
  cut_notes: string | null
  characters: string | null
  key_assets: string | null
  lines_en: string | null
  side: 'north' | 'south' | null
  final_file_id: number | null
  start_sec: number | null
  end_sec: number | null
  shots_count: number
  shots_sec: number
  delta_sec: number
  done_shots: number
  ready_pct: number
  preview: Preview | null
}

export interface ShotAssetRef {
  asset_id: number
  code: string
  name: string
  type: string
  state_id: number | null
  state_name: string | null
}

export interface Shot extends Work {
  id: number
  project_id: number
  scene_id: number
  scene_number: number
  code: string
  order: number
  description: string | null
  size: string | null
  camera: string | null
  sound_note: string | null
  duration_sec: number
  tool: string | null
  stage: string | null
  takes_count: number
  side: 'north' | 'south' | null
  final_file_id: number | null
  assets: ShotAssetRef[]
  files_count: number
  preview: Preview | null
}

export interface SoundCue extends Work {
  id: number
  code: string
  type: string
  who: string | null
  text_en: string | null
  text_ru: string | null
  rights: string | null
  start_offset_sec: number
  scene_id: number | null
  shot_id: number | null
  scene_number: number | null
  shot_code: string | null
}

export interface ShotDetail extends Shot {
  scene: { id: number; number: number; title: string } | null
  sound: SoundCue[]
  setups: { id: number; number: number; motif: string; role: 'setup' | 'payoff' }[]
}

export interface AssetState {
  id: number
  asset_id: number
  name: string
  order: number
  description: string | null
  files_count: number
  preview: Preview | null
}

export interface Asset extends Work {
  id: number
  code: string
  type: string
  name: string
  description: string | null
  side: 'north' | 'south' | null
  states: AssetState[]
  shots_count: number
  files_count: number
  preview: Preview | null
}

export interface AssetDetail extends Asset {
  shots: { id: number; code: string; state_id: number | null }[]
}

export interface Setup extends Work {
  id: number
  number: number | null
  motif: string
  setup_shot_ids: number[]
  payoff_shot_ids: number[]
  setup_shots: { id: number; code: string }[]
  payoff_shots: { id: number; code: string }[]
  reader_takeaway: string | null
  risk: string | null
}

export interface Task extends Work {
  id: number
  code: string
  block: string | null
  title: string
}

export interface Meta {
  status: string[]
  priority: string[]
  stage: string[]
  size: string[]
  tool: string[]
  asset_type: string[]
  sound_type: string[]
  task_block: string[]
  purpose: string[]
  side: string[]
  role: string[]
}

export interface Person {
  id: number
  name: string
  color: string
  has_avatar: boolean
}

export interface FileItem {
  id: number
  kind: 'video' | 'image' | 'audio' | 'document' | 'link'
  source: 'upload' | 'telegram' | 'link'
  original_name: string | null
  mime: string | null
  size_bytes: number | null
  sha256: string | null
  duration_sec: number | null
  width: number | null
  height: number | null
  fps: number | null
  ai_tool: string | null
  ai_prompt: string | null
  ai_seed: string | null
  /** Для ссылок: адрес и заголовок со страницы (Open Graph). */
  url: string | null
  link_title: string | null
  /** Для файлов из Telegram: тема, автор сообщения в чате и ссылка «Открыть в Telegram». */
  tg: { topic_id: number | null; topic_title: string | null; message_id: number; author: string | null; url: string | null } | null
  uploaded_at: string
  uploaded_by: Person | null
  processing: boolean
  error: string | null
  urls: Partial<Record<'original' | 'thumb' | 'preview' | 'poster' | 'play' | 'waveform', string>>
}

export interface Attached {
  attachment_id: number
  purpose: string
  attached_at: string
  attached_by: Person | null
  file: FileItem
}

export interface CommentItem {
  id: number
  entity_type: string
  entity_id: number
  body: string
  mentions: number[]
  at_time_sec: number | null
  created_by: number | null
  created_at: string
  author: Person | null
}

export interface ActivityItem {
  id: number
  at: string
  action: string
  entity_type: string
  entity_id: number | null
  label: string | null
  diff: Record<string, unknown> | null
  actor: Person | null
}

export interface ActivityPage {
  items: ActivityItem[]
  next_before_id: number | null
}

export interface DuplicateInfo {
  file_id: number
  original_name: string | null
  uploaded_by: string | null
  uploaded_at: string
  attached_to: string[]
}

export interface LibraryItem extends FileItem {
  attachments_count: number
  attachments: { entity_type: string; entity_id: number; purpose: string; label: string | null }[]
}

export interface LibraryPage {
  items: LibraryItem[]
  total: number
  next_before_id: number | null
}
