import { test as base, expect, type BrowserContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { BASE_URL, sessionCookie } from './session.mjs'

type Role = 'owner' | 'director' | 'team' | 'guest'

const PEOPLE: Record<Role, { name: string; tgId: number; username: string }> = {
  owner: { name: 'Артём', tgId: 900001, username: 'artem' },
  director: { name: 'Дина', tgId: 900002, username: 'dina' },
  team: { name: 'Петя', tgId: 900003, username: 'petya' },
  guest: { name: 'Гость', tgId: 900004, username: 'guest' },
}

export async function signIn(context: BrowserContext, role: Role = 'owner') {
  const value = sessionCookie({ ...PEOPLE[role], role })
  await context.addCookies([{ name: 'bs_session', value, url: BASE_URL, httpOnly: true }])
}

export const test = base.extend<{ asRole: (role: Role) => Promise<void> }>({
  asRole: async ({ context }, use) => {
    await use((role) => signIn(context, role))
  },
})

export { expect }

/** JSON-запрос к API от имени уже вошедшего в этом контексте пользователя. */
export async function api<T = unknown>(page: Page, method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', url: string, data?: unknown): Promise<T> {
  const res = await page.context().request.fetch(`${BASE_URL}/api${url}`, { method, data })
  if (!res.ok()) throw new Error(`${method} ${url} → ${res.status()} ${await res.text()}`)
  return (res.status() === 204 ? null : await res.json()) as T
}

export interface ShotRef {
  id: number
  code: string
  scene_id: number
  status: string
  description: string | null
  order: number
}

/** Шот по коду; заодно возвращает его в исходное состояние, чтобы тесты не зависели друг от друга. */
export async function freshShot(page: Page, code: string): Promise<ShotRef> {
  const shots = await api<ShotRef[]>(page, 'GET', '/shots')
  const shot = shots.find((s) => s.code === code)!
  if (shot.status !== 'not_started') await api(page, 'PATCH', `/shots/${shot.id}`, { status: 'not_started' })
  return { ...shot, status: 'not_started' }
}

let media: Record<string, string> | null = null

/** Небольшие настоящие файлы: фото, видео, звук. Создаются один раз за прогон. */
export function sampleMedia(): Record<string, string> {
  if (media) return media
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bs-e2e-'))
  const files = { photo: path.join(dir, 'photo.png'), video: path.join(dir, 'clip.mp4'), audio: path.join(dir, 'tone.wav') }
  const ff = (...a: string[]) => execFileSync('ffmpeg', ['-y', '-v', 'error', ...a])
  ff('-f', 'lavfi', '-i', 'testsrc2=size=800x450', '-frames:v', '1', files.photo)
  ff('-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24:duration=2', '-f', 'lavfi', '-i', 'sine=frequency=330:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', files.video)
  ff('-f', 'lavfi', '-i', 'sine=frequency=220:duration=3', files.audio)
  media = files
  return files
}

/** Уникальный файл: у него своя контрольная сумма, поэтому «дубль» не срабатывает. */
export function uniqueImage(tag: string): string {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bs-e2e-')), `${tag}.png`)
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', `color=c=0x${(Math.abs(hash(tag)) % 0xffffff).toString(16).padStart(6, '0')}:size=320x180`, '-frames:v', '1', file])
  return file
}

/** Уникальное короткое видео (своя частота тона → своя контрольная сумма): для версий файла. */
export function uniqueVideo(tag: string): string {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bs-e2e-')), `${tag}.mp4`)
  const freq = 200 + (Math.abs(hash(tag)) % 600)
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', `testsrc2=size=320x180:rate=24:duration=1`, '-f', 'lavfi', '-i', `sine=frequency=${freq}:duration=1`, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', file])
  return file
}

function hash(text: string): number {
  let h = 0
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) | 0
  return h
}

/** Загрузка файла прямо через API (как делает клиент: инициализация → куски → завершение). */
export async function uploadViaApi(
  page: Page,
  filePath: string,
  target?: { entityType: string; entityId: number; purpose?: string },
): Promise<{ file: { id: number; original_name: string } }> {
  const data = fs.readFileSync(filePath)
  const init = await api<{ id: string }>(page, 'POST', '/uploads', { name: path.basename(filePath), size: data.length })
  const sent = await page.context().request.patch(`${BASE_URL}/api/uploads/${init.id}`, {
    data,
    headers: { 'Upload-Offset': '0', 'Content-Type': 'application/octet-stream' },
  })
  if (!sent.ok()) throw new Error(`PATCH upload → ${sent.status()} ${await sent.text()}`)
  return api(page, 'POST', `/uploads/${init.id}/complete`, target ? { entity_type: target.entityType, entity_id: target.entityId, purpose: target.purpose ?? 'reference' } : {})
}

/**
 * Плитки дашборда под сгибом строятся при подходе к ним, а по Tab — сразу все (так ходит клавиатура).
 * Tab повторяется, пока заглушек не останется: первое нажатие может прийти раньше, чем плитки
 * успели навесить обработчик клавиши.
 */
export async function mountDashboardTiles(page: Page): Promise<void> {
  await expect(page.getByText(/\d+:\d{2} из \d+:\d{2}/).first()).toBeVisible()
  await expect(async () => {
    await page.keyboard.press('Tab')
    await expect(page.locator('section[aria-label]')).toHaveCount(0, { timeout: 700 })
  }).toPass({ timeout: 10_000 })
}
