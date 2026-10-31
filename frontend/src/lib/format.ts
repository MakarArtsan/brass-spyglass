import { ru } from '@/ru'

/** 73 → «1:13». Для вырезанной сцены (нет времени) — тире. */
export function timecode(sec: number | null | undefined): string {
  if (sec == null) return ru.common.dash
  const total = Math.round(sec)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** Плеерное время с кадрами не нужно: минуты:секунды и десятые. */
export function clock(sec: number): string {
  if (!Number.isFinite(sec)) return '0:00'
  const whole = Math.floor(sec)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

const dateTime = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})
const dateOnly = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })

/** «30.10, 21:40» */
export const formatDateTime = (iso: string): string => dateTime.format(new Date(iso)).replace(',', '')
export const formatDate = (iso: string): string => dateOnly.format(new Date(iso))

export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return ru.common.dash
  const units = ['Б', 'КБ', 'МБ', 'ГБ']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`
}

/** Целые дни до даты (YYYY-MM-DD) от сегодняшнего дня; отрицательное — просрочено. */
export function daysUntil(date: string, now = new Date()): number {
  const target = new Date(`${date}T00:00:00`)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((target.getTime() - today.getTime()) / 86_400_000)
}

export const num = (value: number | null | undefined): string =>
  value == null ? ru.common.dash : String(Math.round(value * 100) / 100)
