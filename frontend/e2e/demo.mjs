// Демо-данные для скриншотов: немного файлов, статусов и комментариев через обычный API.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { BASE_URL } from './session.mjs'

const ffmpeg = (...args) => execFileSync('ffmpeg', ['-y', '-v', 'error', ...args])

export function makeMedia() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bs-demo-'))
  const files = { clip: path.join(dir, 'Два зеркала — дубль 1.mp4'), still: path.join(dir, 'Референс пролива.png'), tone: path.join(dir, 'Скрип трубы.wav'), clip2: path.join(dir, 'Дубль 2.mp4') }
  ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=24:duration=3', '-f', 'lavfi', '-i', 'sine=frequency=330:duration=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', files.clip)
  ffmpeg('-f', 'lavfi', '-i', 'mandelbrot=size=1280x720', '-frames:v', '1', files.still)
  ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=220:duration=4', files.tone)
  ffmpeg('-f', 'lavfi', '-i', 'smptebars=size=1280x720:rate=24:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', files.clip2)
  return files
}

async function call(cookie, method, url, body, extra = {}) {
  const res = await fetch(BASE_URL + url, {
    method,
    headers: { Cookie: `bs_session=${cookie}`, ...(body && !(body instanceof Uint8Array) ? { 'Content-Type': 'application/json' } : {}), ...extra },
    body: body instanceof Uint8Array ? body : body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok && res.status !== 409) throw new Error(`${method} ${url} → ${res.status} ${await res.text()}`)
  return res.status === 204 ? null : res.json().catch(() => null)
}

async function upload(cookie, file, target) {
  const data = new Uint8Array(fs.readFileSync(file))
  const init = await call(cookie, 'POST', '/api/uploads', { name: path.basename(file), size: data.length })
  await call(cookie, 'PATCH', `/api/uploads/${init.id}`, data, { 'Upload-Offset': '0', 'Content-Type': 'application/octet-stream' })
  return call(cookie, 'POST', `/api/uploads/${init.id}/complete`, { ...target, force: true })
}

export async function seedDemo(cookie) {
  const media = makeMedia()
  const shots = await call(cookie, 'GET', '/api/shots')
  const first = shots.find((s) => s.code === '01.01')
  const second = shots.find((s) => s.code === '01.03')
  await upload(cookie, media.clip, { entity_type: 'shot', entity_id: first.id, purpose: 'take' })
  await upload(cookie, media.clip2, { entity_type: 'shot', entity_id: first.id, purpose: 'take' })
  await upload(cookie, media.still, { entity_type: 'shot', entity_id: first.id, purpose: 'reference' })
  await upload(cookie, media.tone, { entity_type: 'shot', entity_id: first.id, purpose: 'reference' })
  await upload(cookie, media.still, { entity_type: 'shot', entity_id: second.id, purpose: 'reference' })
  const assets = await call(cookie, 'GET', '/api/assets')
  const sheep = assets.find((a) => a.code === 'AN-01')
  await upload(cookie, media.still, { entity_type: 'asset_state', entity_id: sheep.states[1].id, purpose: 'reference' })

  // статусы разных цветов, чтобы список выглядел живым
  const cycle = ['done', 'done', 'in_progress', 'review', 'rework', 'in_progress', 'done', 'not_started']
  for (const [i, s] of shots.slice(0, 18).entries()) await call(cookie, 'PATCH', `/api/shots/${s.id}`, { status: cycle[i % cycle.length] })
  await call(cookie, 'POST', '/api/comments', { entity_type: 'shot', entity_id: first.id, body: 'Нужен ракурс чуть ниже, чтобы обе трубы были в кадре.' })
  // ждём, пока воркер доделает превью
  for (let i = 0; i < 60; i++) {
    const files = await call(cookie, 'GET', `/api/files?entity_type=shot&entity_id=${first.id}`)
    if (files.every((f) => !f.file.processing)) break
    await new Promise((r) => setTimeout(r, 500))
  }
  return { firstShot: first.id, sheep: sheep.id, scene: first.scene_id }
}
