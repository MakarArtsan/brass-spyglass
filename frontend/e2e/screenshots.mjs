// Скриншоты ключевых экранов на ширине ПК (1440) и телефона (390). Запуск: npm run shots
import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'
import { seedDemo } from './demo.mjs'
import { BASE_URL, sessionCookie } from './session.mjs'

const out = process.argv[2] ?? 'screenshots'
fs.mkdirSync(out, { recursive: true })


// --- этап 2: наполнение дашборда и подмена Telegram для скриншотов ---------------------------------------------
import zlib from 'node:zlib'

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})
const crc32 = (buf) => {
  let c = 0xffffffff
  for (const b of buf) c = crcTable[(c ^ b) & 255] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}
const chunk = (type, data) => {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([len, body, crc])
}
/** Градиентная картинка для миниатюр: настоящий PNG без внешних библиотек. */
function gradientPng(hue, size = 160) {
  const raw = Buffer.alloc((size * 3 + 1) * size)
  for (let y = 0; y < size; y++) {
    raw[y * (size * 3 + 1)] = 0
    for (let x = 0; x < size; x++) {
      const o = y * (size * 3 + 1) + 1 + x * 3
      raw[o] = Math.min(255, 40 + hue + (x * 120) / size)
      raw[o + 1] = Math.min(255, 70 + (y * 130) / size)
      raw[o + 2] = Math.min(255, 110 + ((255 - hue) * (x + y)) / (2 * size))
    }
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8
  ihdr[9] = 2
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))])
}

async function seedActivity(cookieOwner) {
  const people = {
    owner: cookieOwner,
    director: sessionCookie({ name: 'Дина', tgId: 900002, username: 'dina', role: 'director' }),
    team: sessionCookie({ name: 'Петя', tgId: 900003, username: 'petya', role: 'team' }),
  }
  const call = async (who, method, url, body) => {
    const r = await fetch(`${BASE_URL}/api${url}`, { method, headers: { Cookie: `bs_session=${people[who]}`, 'Content-Type': 'application/json', Origin: BASE_URL }, body: body ? JSON.stringify(body) : undefined })
    if (!r.ok) throw new Error(`${method} ${url} ${r.status} ${await r.text()}`)
    return r.status === 204 ? null : r.json()
  }
  const shots = await call('owner', 'GET', '/shots')
  const me = (await call('owner', 'GET', '/me')).user.id
  const statuses = ['done', 'done', 'done', 'review', 'in_progress', 'done', 'rework', 'done', 'in_progress', 'done', 'done', 'review', 'done', 'done']
  for (const [i, st] of statuses.entries()) await call(['owner', 'director', 'team'][i % 3], 'PATCH', `/shots/${shots[i].id}`, { status: st })
  await call('owner', 'POST', '/comments', { entity_type: 'shot', entity_id: shots[2].id, body: 'Проверить дистанцию камеры' })
  await call('director', 'POST', '/comments', { entity_type: 'shot', entity_id: shots[3].id, body: 'Нужен второй дубль' })
  const tasks = (await call('owner', 'GET', '/tasks')).filter((t) => !['done', 'cut'].includes(t.status))
  await call('owner', 'PATCH', `/tasks/${tasks[0].id}`, { assignee_id: me, due_date: '2026-11-03' })
  await call('owner', 'PATCH', `/tasks/${tasks[1].id}`, { assignee_id: me, due_date: '2026-10-20' })
  await call('owner', 'PATCH', `/tasks/${tasks[2].id}`, { assignee_id: me })
}

const TG_ITEMS = Array.from({ length: 24 }, (_, i) => 24 - i).map((id) => ({
  id, message_id: 2000 + id, topic_id: 5,
  kind: id === 21 ? 'video' : id === 19 ? 'link' : 'image',
  mime: id === 21 ? 'video/mp4' : 'image/jpeg',
  caption: id === 19 ? 'Референс по свету' : ['Дозорный Севера', 'Овца, полосатая', 'Глашатай на площади', 'Труба крупно', 'Стена-крепость', 'Туман над проливом'][id % 6],
  file_name: null, url: id === 19 ? 'https://example.com/ref' : null,
  grouped_id: id === 23 || id === 22 ? 555 : null,
  author_name: ['Лена', 'Петя', 'Дина'][id % 3], posted_at: `2026-10-30T${String(8 + (id % 14)).padStart(2, '0')}:10:00Z`,
  size_bytes: 1000, duration_sec: id === 21 ? 12 : null,
  thumb_url: id === 19 ? null : `/api/tg/media/${id}/thumb?t=x`, imported_file_id: id === 20 ? 9 : null,
  open_url: `https://t.me/c/1234567890/5/${2000 + id}`,
}))
const TG_TOPICS = [
  { topic_id: 5, title: 'Персонажи', icon_emoji: null, media_count: 24, last_synced_at: '2026-10-30T12:00:00Z', history_complete: true, latest_thumb_url: '/api/tg/media/24/thumb?t=x' },
  { topic_id: 9, title: 'Локации', icon_emoji: null, media_count: 17, last_synced_at: '2026-10-30T12:00:00Z', history_complete: true, latest_thumb_url: '/api/tg/media/3/thumb?t=x' },
  { topic_id: 12, title: 'Звук и музыка', icon_emoji: null, media_count: 6, last_synced_at: '2026-10-30T12:00:00Z', history_complete: false, latest_thumb_url: null },
]

async function mockTelegram(page) {
  const json = (route, body) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  await page.route((u) => u.pathname === '/api/tg/topics', (r) => json(r, TG_TOPICS))
  await page.route((u) => u.pathname.endsWith('/thumb'), (r) => r.fulfill({ contentType: 'image/png', body: gradientPng(Number(r.request().url().match(/media\/(\d+)\//)?.[1] ?? 1) * 9) }))
  await page.route((u) => u.pathname === '/api/tg/media', (r) => json(r, { items: TG_ITEMS, next_before_id: null }))
  await page.route((u) => u.pathname === '/api/tg/jobs', (r) => json(r, []))
  await page.route((u) => u.pathname === '/api/tg/status', (r) => json(r, {
    configured: true, connected: true, chat_id: -1001234567890, syncing: true, phase: 'thumbs', topic: null, thumbs_left: 23,
    last_error: null, last_run_at: '2026-10-30T12:00:00Z', overview: { topics: 3, media: 47, topics_complete: 2, last_synced_at: '2026-10-30T12:00:00Z' },
  }))
}

const cookie = sessionCookie()
const demo = await seedDemo(cookie)
await seedActivity(cookie)
const browser = await chromium.launch()

async function shoot(name, viewport, setup, { mobile = false } = {}) {
  const ctx = await browser.newContext({ viewport, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: mobile ? 2 : 1 })
  if (setup.auth !== false) {
    await ctx.addCookies([{ name: 'bs_session', value: cookie, url: BASE_URL, httpOnly: true }])
  }
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.error('PAGE ERROR', name, e.message))
  page.on('console', (m) => m.type() === 'error' && console.error('CONSOLE', name, m.text()))
  if (setup.before) await setup.before(page)
  await page.goto(BASE_URL + setup.url)
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => document.fonts.ready)
  if (setup.act) await setup.act(page)
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: setup.fullPage ?? false })
  await ctx.close()
}

/** Плитки дашборда под сгибом строятся при подходе; для снимка целиком строим их по Tab, как клавиатура. */
async function mountTiles(page) {
  await page.waitForSelector('text=/\\d+:\\d{2} из \\d+:\\d{2}/')
  for (let i = 0; i < 6 && (await page.locator('section[aria-label]').count()) > 0; i++) {
    await page.keyboard.press('Tab')
    await page.waitForTimeout(250)
  }
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(600)
}

const desktop = { width: 1440, height: 900 }
const phone = { width: 390, height: 844 }

for (const [label, viewport, mobile] of [['desktop', desktop, false], ['phone', phone, true]]) {
  await shoot(`${label}-login`, viewport, { url: '/login', auth: false }, { mobile })
  await shoot(`${label}-dashboard`, viewport, { url: '/', fullPage: true, act: mountTiles }, { mobile })
  await shoot(`${label}-media`, viewport, { url: '/media' }, { mobile })
  await shoot(`${label}-telegram-screen`, viewport, { url: '/telegram', before: mockTelegram }, { mobile })
  await shoot(`${label}-scenes`, viewport, { url: '/scenes' }, { mobile })
  await shoot(`${label}-scene-detail`, viewport, { url: `/scenes/${demo.scene}`, fullPage: true }, { mobile })
  await shoot(`${label}-shots`, viewport, { url: '/shots' }, { mobile })
  await shoot(`${label}-shot-card`, viewport, { url: `/shots?shot=${demo.firstShot}` }, { mobile })
  await shoot(`${label}-assets`, viewport, { url: '/assets' }, { mobile })
  await shoot(`${label}-asset-card`, viewport, { url: `/assets?asset=${demo.sheep}` }, { mobile })
  await shoot(`${label}-setups`, viewport, { url: '/setups' }, { mobile })
  await shoot(`${label}-sound`, viewport, { url: '/sound' }, { mobile })
  await shoot(`${label}-tasks`, viewport, { url: '/tasks' }, { mobile })
  await shoot(`${label}-journal`, viewport, { url: '/journal' }, { mobile })
  await shoot(`${label}-brand`, viewport, { url: '/brand', fullPage: true }, { mobile })
}

await shoot('desktop-telegram-window', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  before: mockTelegram,
  act: async (p) => {
    await p.getByRole('button', { name: 'Из Telegram' }).first().click()
    const dialog = p.getByRole('dialog', { name: 'Добавить из Telegram' })
    await dialog.getByRole('button', { name: /Отметить: Дозорный Севера/ }).first().click()
    await dialog.getByLabel(/Весь альбом/).check()
    await p.waitForTimeout(500)
  },
})
await shoot('phone-telegram-window', phone, {
  url: `/shots?shot=${demo.firstShot}`,
  before: mockTelegram,
  act: async (p) => {
    await p.getByRole('button', { name: 'Из Telegram' }).first().click()
    const dialog = p.getByRole('dialog', { name: 'Добавить из Telegram' })
    await dialog.getByRole('button', { name: /Персонажи/ }).click()
    await p.waitForTimeout(500)
  },
}, { mobile: true })
await shoot('desktop-media-picker', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  act: async (p) => {
    await p.getByRole('button', { name: 'Из медиатеки' }).first().click()
    await p.waitForTimeout(800)
  },
})
await shoot('desktop-status-menu', desktop, {
  url: '/shots',
  act: (p) => p.locator('tr[data-shot="01.04"]').getByRole('button', { name: /Статус/ }).click(),
})
await shoot('desktop-viewer-video', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  act: async (p) => {
    await p.getByRole('button', { name: /Открыть: Два зеркала/ }).first().click()
    await p.waitForTimeout(600)
  },
})
await shoot('desktop-viewer-audio', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  act: async (p) => {
    await p.getByRole('button', { name: /Открыть: Скрип трубы/ }).first().click()
    await p.waitForTimeout(1200)
  },
})
await shoot('desktop-lens-tile', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  act: (p) => p.getByRole('button', { name: /Открыть: Референс пролива/ }).first().hover(),
})
await shoot('phone-bottom-sheet-more', phone, { url: '/', act: (p) => p.getByRole('button', { name: 'Ещё' }).click() }, { mobile: true })

await browser.close()
console.log('готово →', out)
