import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Дополнить нулём слева: 7 → «07». */
export const pad2 = (n: number) => String(n).padStart(2, '0')

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
}

/** Цвет токена бренда для кода, который рисует сам (canvas, wavesurfer). */
export const cssColor = (token: string): string =>
  `rgb(${getComputedStyle(document.documentElement).getPropertyValue(`--${token}`).trim()})`
