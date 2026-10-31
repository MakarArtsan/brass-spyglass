import { formatDate } from '@/lib/format'
import type { ActivityItem } from '@/lib/types'
import { ru } from '@/ru'

const dictionaries: Record<string, Record<string, string>> = {
  status: ru.status,
  priority: ru.priority,
  stage: ru.stage,
  size: ru.size,
  tool: ru.tool,
  block: ru.taskBlock,
  role: ru.roles,
  side: ru.side,
}

/** Значение поля в человеческом виде: слаг справочника → русский текст, дата → дд.мм.гггг. */
export function formatValue(field: string, value: unknown, entityType?: string): string {
  if (value === null || value === undefined || value === '') return ru.common.dash
  const text = String(value)
  if (field === 'type') {
    const dict = entityType === 'asset' ? ru.assetType : entityType === 'sound_cue' ? ru.soundType : undefined
    return dict?.[text as keyof typeof dict] ?? text
  }
  if (dictionaries[field]) return dictionaries[field][text] ?? text
  if (field === 'due_date' && /^\d{4}-\d{2}-\d{2}/.test(text)) return formatDate(text)
  return text.length > 60 ? `${text.slice(0, 57)}…` : text
}

export interface Described {
  /** Короткое название действия: «статус», «изменение», «файл привязан». */
  kind: string
  /** Подробности: пары «поле: было → стало». */
  details: string[]
}

/** Журнал показывает действие, а не готовую фразу: так не нужно угадывать род глагола. */
export function describe(item: ActivityItem): Described {
  const diff = item.diff ?? {}
  const kind = (ru.journal.actions as Record<string, string>)[item.action] ?? item.action
  const details: string[] = []

  switch (item.action) {
    case 'status':
    case 'update': {
      for (const [field, change] of Object.entries(diff)) {
        const label = ru.fields[field] ?? field
        if (Array.isArray(change) && change.length === 2) {
          details.push(`${label}: ${formatValue(field, change[0], item.entity_type)} → ${formatValue(field, change[1], item.entity_type)}`)
        }
      }
      break
    }
    case 'create': {
      const title = diff.code ?? diff.title ?? diff.name ?? diff.motif ?? diff.body
      if (title) details.push(String(title))
      break
    }
    case 'reorder':
      details.push(ru.journal.reordered)
      break
    case 'import': {
      const created = Object.values((diff.created as Record<string, number>) ?? {}).reduce((a, b) => a + b, 0)
      details.push(ru.journal.importSummary(created, Number(diff.warnings_total ?? 0)))
      break
    }
    case 'link':
    case 'unlink':
      if (diff.asset) details.push(String(diff.asset))
      break
    case 'attach':
    case 'detach':
      details.push([diff.file, diff.purpose ? ru.purpose[diff.purpose as keyof typeof ru.purpose] : null].filter(Boolean).join(' · '))
      break
    case 'login':
      if (diff.created) details.push(ru.journal.loginNew)
      break
  }
  return { kind, details }
}
