import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { apiPath } from '@/lib/project'
import type { Person } from '@/lib/types'
import { ru } from '@/ru'

export type IssueLevel = 'error' | 'warning' | 'fix'

export interface ImportIssue {
  level: IssueLevel
  message: string
  /** Адрес по-человечески: «Сцена 4, шот 3». Пусто, если замечание ко всему файлу. */
  where: string
}

export interface PreviewShot {
  position: number
  description: string
  size: string | null
  duration_sec: number
  dialogue: { who: string | null; text: string }[]
}

export interface PreviewScene {
  number: number
  title: string
  summary: string | null
  planned_sec: number
  shots_sec: number
  location: string | null
  shots: PreviewShot[]
}

export interface PreviewCard {
  code: string
  name: string
  kind: string | null
  description: string | null
  states: string[]
  shots: number
  scenes: number
}

export interface ImportPreview {
  title: string
  title_en: string | null
  logline: string | null
  language: string
  schema_version: string
  counts: Record<'scenes' | 'shots' | 'characters' | 'locations' | 'assets' | 'dialogue' | 'setups' | 'open_questions', number>
  total_sec: number
  shots_sec: number
  target_min_sec: number | null
  target_max_sec: number | null
  in_target: boolean | null
  scenes: PreviewScene[]
  characters: PreviewCard[]
  locations: PreviewCard[]
  assets: PreviewCard[]
  open_questions: { question: string; related: string[] }[]
}

export interface ImportCheck {
  ok: boolean
  can_apply: boolean
  empty: boolean
  not_empty_reason: string | null
  parts: number
  issues: ImportIssue[]
  errors: number
  warnings: number
  fixes: number
  preview: ImportPreview | null
}

export interface ImportParams {
  target_min_sec?: number
  target_max_sec?: number
  max_shot_sec?: number
}

export interface ImportRunItem {
  id: number
  created_at: string
  created_by: Person | null
  filename: string | null
  schema_version: string
  parts: number
  created: Record<string, number>
  warnings: number
}

export interface ImportApplied {
  run: ImportRunItem
  created: Record<string, number>
  warnings: number
  slug: string
}

/** Адрес скачивания промпта (обычная ссылка: браузер сам сохранит файл). */
export function promptUrl(params: ImportParams, language: string): string {
  const query = new URLSearchParams({ language })
  for (const [key, value] of Object.entries(params)) if (value !== undefined) query.set(key, String(value))
  return `/api${apiPath('/import/prompt')}?${query}`
}

export const exampleUrl = (): string => `/api${apiPath('/import/example')}`
export const sourceUrl = (runId: number): string => `/api${apiPath(`/import/runs/${runId}/source`)}`

/** Текст промпта для буфера обмена. */
export async function fetchPrompt(params: ImportParams, language: string): Promise<string> {
  const res = await fetch(promptUrl(params, language), { credentials: 'same-origin' })
  if (!res.ok) throw new Error(String(res.status))
  return res.text()
}

export const useCheckImport = () =>
  useMutation({
    mutationFn: (body: ImportParams & { texts: string[] }) =>
      api<ImportCheck>('/import/check', { method: 'POST', body: JSON.stringify(body) }),
  })

export const useImportRuns = () =>
  useQuery({ queryKey: ['import', 'runs'] as const, queryFn: () => api<ImportRunItem[]>('/import/runs') })

export function useApplyImport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ImportParams & { texts: string[]; exclude: string[]; names: string[] }) =>
      api<ImportApplied>('/import/apply', { method: 'POST', body: JSON.stringify(body) }),
    // Появились сцены, шоты, ассеты, звук, задачи: всё, что показывают разделы, надо прочитать заново.
    onSuccess: () => void qc.invalidateQueries(),
  })
}

/** Поля формы промпта как их ввёл человек: пустое — «как в проекте». */
export interface PromptForm {
  min: string
  max: string
  shot: string
  language: string
}

/** Пустое или нечисловое поле не передаём: сервер подставит цели проекта. */
export function paramsOf(form: PromptForm): ImportParams {
  const num = (v: string) => (v.trim() !== '' && Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : undefined)
  return { target_min_sec: num(form.min), target_max_sec: num(form.max), max_shot_sec: num(form.shot) }
}

const issueLine = (i: ImportIssue) => (i.where ? `${i.where}: ${i.message}` : i.message)

/** Сообщение для LLM: что исправить в JSON. Вставляется в тот же чат, где получили файл. */
export function errorsForLlm(issues: ImportIssue[]): string {
  const errors = issues.filter((i) => i.level === 'error').map((i) => `- ${issueLine(i)}`)
  return `${ru.importPage.llm.head}\n${errors.join('\n')}\n\n${ru.importPage.llm.tail}`
}
