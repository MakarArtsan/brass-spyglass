import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

interface TextProps {
  value: string | number | null
  onSave: (value: string | null) => void
  readOnly?: boolean
  multiline?: boolean
  numeric?: boolean
  mono?: boolean
  placeholder?: string
  ariaLabel: string
  className?: string
}

/**
 * Инлайн-правка: клик (или тап) превращает текст в поле. Enter сохраняет, Esc отменяет,
 * уход из поля тоже сохраняет. У многострочного поля сохраняет Ctrl/Cmd+Enter.
 */
export function EditableText({
  value,
  onSave,
  readOnly,
  multiline,
  numeric,
  mono,
  placeholder = ru.common.dash,
  ariaLabel,
  className,
}: TextProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const field = useRef<HTMLInputElement & HTMLTextAreaElement>(null)
  const text = value == null ? '' : String(value)

  useEffect(() => {
    if (editing) {
      field.current?.focus()
      field.current?.select?.()
    }
  }, [editing])

  const commit = () => {
    setEditing(false)
    const next = draft.trim()
    if (next !== text.trim()) onSave(next === '' ? null : next)
  }

  if (!editing) {
    return (
      <button
        type="button"
        disabled={readOnly}
        aria-label={ariaLabel}
        onClick={() => {
          setDraft(text)
          setEditing(true)
        }}
        className={cn(
          'block min-h-touch w-full rounded-md px-2 py-2 text-left text-sm transition-colors duration-fast',
          !readOnly && 'hover:bg-ink/60',
          readOnly && 'cursor-default',
          mono && 'mono',
          !text && 'text-fog',
          className,
        )}
      >
        {text || placeholder}
      </button>
    )
  }
  const shared = {
    ref: field,
    value: draft,
    'aria-label': ariaLabel,
    onChange: (e: React.ChangeEvent<HTMLInputElement & HTMLTextAreaElement>) => setDraft(e.target.value),
    onBlur: commit,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') setEditing(false)
      else if (e.key === 'Enter' && (!multiline || e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        commit()
      }
    },
    className: cn(
      'w-full rounded-md border border-brass bg-ink px-2 py-2 text-sm outline-none',
      mono && 'mono',
      className,
    ),
  }
  return multiline ? (
    <textarea {...shared} rows={Math.min(8, Math.max(3, Math.ceil(draft.length / 48)))} />
  ) : (
    <input {...shared} type={numeric ? 'number' : 'text'} inputMode={numeric ? 'decimal' : undefined} step={numeric ? 'any' : undefined} />
  )
}

interface SelectProps {
  value: string | null
  options: { value: string; label: string }[]
  onChange: (value: string | null) => void
  readOnly?: boolean
  ariaLabel: string
  /** Показывать пустой пункт «—» (для необязательных полей). */
  allowEmpty?: boolean
  className?: string
}

/** Список значений справочника: на телефоне открывается родной выбор — это быстрее всего. */
export function EditableSelect({ value, options, onChange, readOnly, ariaLabel, allowEmpty = true, className }: SelectProps) {
  if (readOnly) {
    const label = options.find((o) => o.value === value)?.label
    return <span className={cn('block px-2 py-2 text-sm', !label && 'text-fog', className)}>{label ?? ru.common.dash}</span>
  }
  return (
    <select
      aria-label={ariaLabel}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      className={cn(
        'min-h-touch w-full cursor-pointer appearance-none rounded-md bg-transparent px-2 py-2 text-sm outline-none transition-colors duration-fast hover:bg-ink/60 focus-visible:bg-ink',
        !value && 'text-fog',
        className,
      )}
    >
      {allowEmpty && <option value="">{ru.common.dash}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value} className="bg-chart text-paper">
          {o.label}
        </option>
      ))}
    </select>
  )
}
