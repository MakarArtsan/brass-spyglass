import type { Page, Route } from '@playwright/test'
import { expect, freshShot, test } from './fixtures'

// Настоящего Telegram в e2e нет: сетевые ответы /api/tg/* подменяются. Серверную часть (индекс, импорт,
// дубли, права) проверяют pytest-тесты на подставном шлюзе; здесь — поведение окна и экрана.

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

interface Item {
  id: number
  message_id: number
  topic_id: number
  kind: 'image' | 'video' | 'audio' | 'document' | 'link'
  mime: string | null
  caption: string | null
  file_name: string | null
  url: string | null
  grouped_id: number | null
  author_name: string
  posted_at: string
  size_bytes: number | null
  duration_sec: number | null
  thumb_url: string | null
  imported_file_id: number | null
  open_url: string
}

const item = (id: number, over: Partial<Item> = {}): Item => ({
  id,
  message_id: 1000 + id,
  topic_id: 5,
  kind: 'image',
  mime: 'image/jpeg',
  caption: `Подпись ${id}`,
  file_name: null,
  url: null,
  grouped_id: null,
  author_name: 'Лена',
  posted_at: `2026-10-30T${String(10 + (id % 12)).padStart(2, '0')}:00:00Z`,
  size_bytes: 1000,
  duration_sec: null,
  thumb_url: `/api/tg/media/${id}/thumb?t=x`,
  imported_file_id: null,
  open_url: `https://t.me/c/1234567890/5/${1000 + id}`,
  ...over,
})

// 30 сообщений темы «Персонажи», новые первыми: 30…1; 28–27 — альбом, 26 — видео, 25 — ссылка, 24 — уже на сайте
const ITEMS: Item[] = Array.from({ length: 30 }, (_, i) => 30 - i).map((id) => {
  if (id === 28 || id === 27) return item(id, { grouped_id: 777 })
  if (id === 26) return item(id, { kind: 'video', mime: 'video/mp4', duration_sec: 12 })
  if (id === 25) return item(id, { kind: 'link', url: 'https://example.com/ref', thumb_url: null, caption: 'Референс по свету' })
  if (id === 24) return item(id, { imported_file_id: 9 })
  return item(id)
})

const TOPICS = [
  { topic_id: 5, title: 'Персонажи', icon_emoji: null, media_count: 30, last_synced_at: '2026-10-30T12:00:00Z', history_complete: true, latest_thumb_url: '/api/tg/media/30/thumb?t=x' },
  { topic_id: 9, title: 'Локации', icon_emoji: null, media_count: 4, last_synced_at: '2026-10-30T12:00:00Z', history_complete: false, latest_thumb_url: null },
]

interface Recorder {
  mediaQueries: URLSearchParams[]
  imports: Record<string, unknown>[]
  views: number[]
}

async function mockTelegram(page: Page): Promise<Recorder> {
  const rec: Recorder = { mediaQueries: [], imports: [], views: [] }
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  let jobPolls = 0

  await page.route((url) => url.pathname === '/api/tg/topics', (route) => json(route, TOPICS))
  await page.route((url) => url.pathname.endsWith('/thumb'), (route) => route.fulfill({ status: 200, contentType: 'image/png', body: PNG }))
  await page.route((url) => url.pathname === '/api/tg/media', (route) => {
    const q = new URL(route.request().url()).searchParams
    rec.mediaQueries.push(q)
    const kinds = q.get('kinds')?.split(',').filter(Boolean) ?? []
    const text = (q.get('q') ?? '').toLowerCase()
    const before = q.get('before_id')
    let rows = ITEMS.filter((i) => String(i.topic_id) === (q.get('topic_id') ?? '5'))
    if (kinds.length) rows = rows.filter((i) => kinds.includes(i.kind))
    if (text) rows = rows.filter((i) => (i.caption ?? '').toLowerCase().includes(text))
    if (q.get('hide_imported') === 'true') rows = rows.filter((i) => i.imported_file_id === null)
    if (before) rows = rows.filter((i) => i.id < Number(before))
    const page20 = rows.slice(0, 20)
    return json(route, { items: page20, next_before_id: rows.length > 20 ? page20[page20.length - 1].id : null })
  })
  await page.route((url) => /\/api\/tg\/media\/\d+\/view$/.test(url.pathname), (route) => {
    const id = Number(route.request().url().match(/media\/(\d+)\/view/)![1])
    if (route.request().method() === 'POST') {
      rec.views.push(id)
      return json(route, { ready: true, url: `/api/tg/media/${id}/view?t=x`, job_id: null })
    }
    return route.fulfill({ status: 200, contentType: 'image/png', body: PNG })
  })
  await page.route((url) => url.pathname === '/api/tg/import', async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    rec.imports.push(body)
    return json(route, { job_id: 7, count: (body.media_ids as number[]).length }, 202)
  })
  await page.route((url) => url.pathname === '/api/tg/jobs', (route) => {
    if (rec.imports.length === 0) return json(route, [])
    jobPolls += 1
    const total = (rec.imports[0].media_ids as number[]).length
    const running = jobPolls < 3
    return json(route, [{ id: 7, status: running ? 'running' : 'done', progress: running ? 0.5 : 1, error: null, total, entity_type: 'shot', entity_id: 1 }])
  })
  return rec
}

async function openWindow(page: Page, code = '01.01') {
  const shot = await freshShot(page, code)
  await page.goto(`/shots?shot=${shot.id}`)
  await page.getByRole('button', { name: 'Из Telegram' }).first().click()
  await expect(page.getByRole('dialog', { name: 'Добавить из Telegram' })).toBeVisible()
  return shot
}

test.describe('окно «Добавить из Telegram»', () => {
  test('темы с числом медиа, на ПК сразу открыта первая, на телефоне сначала темы', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await mockTelegram(page)
    await openWindow(page)
    const dialog = page.getByRole('dialog', { name: 'Добавить из Telegram' })
    await expect(dialog.getByRole('button', { name: /Персонажи/ })).toBeVisible()
    await expect(dialog.getByRole('button', { name: /Локации/ })).toBeVisible()
    if (isMobile) {
      await expect(dialog.getByText('Выберите тему слева')).toBeHidden() // на телефоне видны только темы
      await dialog.getByRole('button', { name: /Персонажи/ }).click()
      await expect(dialog.getByRole('button', { name: /К темам/ })).toBeVisible()
    }
    await expect(dialog.getByRole('button', { name: /Отметить: Подпись 30/ })).toBeVisible()
  })

  test('фильтр по типу, поиск и «скрыть уже добавленные» уходят в запрос', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const rec = await mockTelegram(page)
    await openWindow(page)
    const dialog = page.getByRole('dialog', { name: 'Добавить из Telegram' })
    if (isMobile) await dialog.getByRole('button', { name: /Персонажи/ }).click()

    await dialog.getByRole('button', { name: 'Видео', exact: true }).click()
    await expect(dialog.getByRole('button', { name: /Отметить: Подпись 26/ })).toBeVisible()
    await expect(dialog.getByRole('button', { name: /Отметить: Подпись 30/ })).toHaveCount(0)
    expect(rec.mediaQueries.at(-1)!.get('kinds')).toBe('video')
    await dialog.getByRole('button', { name: 'Видео', exact: true }).click()

    await dialog.getByRole('searchbox', { name: 'Поиск по подписи в теме' }).fill('Подпись 29')
    await expect(dialog.getByRole('button', { name: /Отметить: Подпись 29/ })).toBeVisible()
    await expect(dialog.getByRole('button', { name: /Отметить: Подпись 30/ })).toHaveCount(0)
    expect(rec.mediaQueries.at(-1)!.get('q')).toBe('Подпись 29')
    await dialog.getByRole('searchbox', { name: 'Поиск по подписи в теме' }).fill('')

    await expect(dialog.getByText('Уже на сайте')).toBeVisible()
    await dialog.getByLabel('Скрыть уже добавленные').check()
    await expect(dialog.getByText('Уже на сайте')).toHaveCount(0)
    expect(rec.mediaQueries.at(-1)!.get('hide_imported')).toBe('true')
  })

  test('альбом отмечается целиком, импорт уходит с карточкой и назначением, прогресс виден в углу', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const rec = await mockTelegram(page)
    const shot = await openWindow(page)
    const dialog = page.getByRole('dialog', { name: 'Добавить из Telegram' })
    if (isMobile) await dialog.getByRole('button', { name: /Персонажи/ }).click()

    await expect(dialog.getByRole('group', { name: 'Альбом · 2' })).toBeVisible()
    await dialog.getByLabel(/Весь альбом/).check()
    await dialog.getByRole('button', { name: /Отметить: Подпись 30/ }).click()
    await expect(dialog.getByRole('button', { name: 'Добавить: 3' })).toBeVisible()

    await dialog.getByLabel('Назначение').selectOption('take')
    await dialog.getByRole('button', { name: 'Добавить: 3' }).click()
    await expect(page.getByRole('dialog', { name: 'Добавить из Telegram' })).toHaveCount(0) // окно можно закрыть: идёт в фоне

    expect(rec.imports).toHaveLength(1)
    expect(rec.imports[0]).toMatchObject({ entity_type: 'shot', entity_id: shot.id, purpose: 'take' })
    expect((rec.imports[0].media_ids as number[]).sort((a, b) => a - b)).toEqual([27, 28, 30])

    const corner = page.getByRole('list', { name: 'Загрузка из Telegram' })
    await expect(corner.getByText('Загружено 2 из 3')).toBeVisible()
    await expect(corner.getByText('Файлы добавлены в карточку')).toBeVisible()
  })

  test('просмотр в окне: фото открывается в полный размер без добавления в проект', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const rec = await mockTelegram(page)
    await openWindow(page)
    const dialog = page.getByRole('dialog', { name: 'Добавить из Telegram' })
    if (isMobile) await dialog.getByRole('button', { name: /Персонажи/ }).click()

    await dialog.getByRole('button', { name: /Посмотреть: Подпись 29/ }).click()
    const viewer = dialog.getByRole('region', { name: 'Посмотреть' })
    await expect(viewer.locator('img[src*="/view"]')).toBeVisible()
    expect(rec.views).toContain(29)
    await viewer.getByRole('button', { name: 'Закрыть' }).click()
    await expect(viewer).toHaveCount(0)
    expect(rec.imports).toHaveLength(0)
  })

  test('ссылку нельзя «посмотреть», только отметить', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await mockTelegram(page)
    await openWindow(page)
    const dialog = page.getByRole('dialog', { name: 'Добавить из Telegram' })
    if (isMobile) await dialog.getByRole('button', { name: /Персонажи/ }).click()
    await expect(dialog.getByRole('button', { name: /Отметить: Референс по свету/ })).toBeVisible()
    await expect(dialog.getByRole('button', { name: /Посмотреть: Референс по свету/ })).toHaveCount(0)
  })

  test('бесконечная прокрутка подгружает следующую страницу темы', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const rec = await mockTelegram(page)
    await openWindow(page)
    const dialog = page.getByRole('dialog', { name: 'Добавить из Telegram' })
    if (isMobile) await dialog.getByRole('button', { name: /Персонажи/ }).click()
    await expect(dialog.getByRole('button', { name: /Отметить: Подпись 30/ })).toBeVisible()
    await dialog.getByRole('button', { name: 'Показать ещё' }).click()
    await expect(dialog.getByRole('button', { name: /Отметить: Подпись 1$/ })).toBeVisible()
    expect(rec.mediaQueries.some((q) => q.has('before_id'))).toBe(true)
  })

  test('гость не видит кнопку Telegram', async ({ page, asRole }) => {
    await asRole('guest')
    const shot = await freshShot(page, '01.02').catch(() => null)
    await page.goto(shot ? `/shots?shot=${shot.id}` : '/shots')
    await expect(page.getByRole('button', { name: 'Из Telegram' })).toHaveCount(0)
  })
})

test.describe('экран «Telegram»', () => {
  test('показывает подключение, синхронизацию и темы; владелец запускает синхронизацию', async ({ page, asRole }) => {
    await asRole('owner')
    await mockTelegram(page)
    let synced = 0
    await page.route((url) => url.pathname === '/api/tg/status', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true, connected: true, chat_id: -1001234567890, syncing: true, phase: 'history', topic: 'Локации',
          thumbs_left: 12, last_error: null, last_run_at: '2026-10-30T12:00:00Z',
          overview: { topics: 2, media: 34, topics_complete: 1, last_synced_at: '2026-10-30T12:00:00Z' },
        }),
      }),
    )
    await page.route((url) => url.pathname === '/api/tg/sync', (route) => {
      synced += 1
      return route.fulfill({ status: 202, contentType: 'application/json', body: '{"started":true}' })
    })
    await page.goto('/telegram')
    await expect(page.getByRole('heading', { name: 'Telegram' }).first()).toBeVisible()
    await expect(page.getByText('Подключён')).toBeVisible()
    await expect(page.getByText(/Идёт чтение чата/)).toBeVisible()
    await expect(page.getByText(/читаем историю · тема «Локации» · превью осталось: 12/)).toBeVisible()
    await expect(page.getByText('Тем: 2 · медиа в индексе: 34')).toBeVisible()
    await expect(page.getByText('история прочитана')).toBeVisible()
    await expect(page.getByText('читается', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Прочитать чат заново' }).click()
    await expect.poll(() => synced).toBe(1)
  })

  test('без настройки объясняет, что делать', async ({ page, asRole }) => {
    await asRole('owner')
    await mockTelegram(page)
    await page.route((url) => url.pathname === '/api/tg/status', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ configured: false, connected: false, chat_id: null, syncing: false, phase: 'idle', topic: null, thumbs_left: 0, last_error: null, last_run_at: null, overview: null }),
      }),
    )
    await page.route((url) => url.pathname === '/api/tg/topics', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }))
    await page.goto('/telegram')
    await expect(page.getByText('Не подключён')).toBeVisible()
    await expect(page.getByText(/TG_SESSION и TG_CHAT_ID/)).toBeVisible()
  })

  test('юзербот настроен, но не подключился: на экране видна причина', async ({ page, asRole }) => {
    await asRole('owner')
    await mockTelegram(page)
    const reason = 'Одну и ту же сессию использовали с двух мест одновременно, и Telegram её аннулировал. Выпустите новую (make_session.py).'
    await page.route((url) => url.pathname === '/api/tg/status', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, connected: false, userbot_error: reason, chat_id: -1001234567890, syncing: false, phase: 'idle', topic: null, thumbs_left: 0, last_error: null, last_run_at: null, overview: null }),
      }),
    )
    await page.route((url) => url.pathname === '/api/tg/topics', (route) => route.fulfill({ contentType: 'application/json', body: '[]' }))
    await page.goto('/telegram')
    await expect(page.getByText('Не подключён')).toBeVisible()
    await expect(page.getByRole('alert').filter({ hasText: 'Причина:' })).toContainText('с двух мест одновременно')
  })

  test('гостю экран не показывается', async ({ page, asRole }) => {
    await asRole('guest')
    await page.goto('/telegram')
    await expect(page.getByText('Раздел доступен участникам, не гостям.')).toBeVisible()
  })
})
