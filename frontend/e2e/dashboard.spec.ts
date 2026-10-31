import { api, expect, freshShot, signIn, test } from './fixtures'

test('дашборд показывает данные проекта из базы', async ({ page, asRole }) => {
  await asRole('owner')
  await page.goto('/')
  await expect(page.getByText('24 fps')).toBeVisible()
  await expect(page.getByText('1920 × 1080')).toBeVisible()
  await expect(page.getByText('5:00–7:00').first()).toBeVisible()
  // Официальный срок: 20.11 до конца суток по Дубаю (23:59) — это 22:59 по Москве.
  await expect(page.getByText('20 ноября 2026 г., 22:59 МСК')).toBeVisible()
  await expect(page.getByText('20 ноября, 23:59 по Дубаю')).toBeVisible()
  await expect(page.getByText('18 ноября 2026 г., 22:59 МСК')).toBeVisible()
})

interface TaskRef {
  id: number
  code: string
  status: string
  due_date: string | null
}

/** Плитки под сгибом строятся при подходе к ним; Tab строит их сразу, это ровно то, что делает клавиатурный пользователь. */
async function mountAllTiles(page: import('@playwright/test').Page) {
  await expect(page.getByText(/\d+:\d{2} из \d+:\d{2}/).first()).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.locator('section[aria-label]')).toHaveCount(0)
}

test.describe('виджеты дашборда', () => {
  test('кольцо готовности у второго пользователя меняется без перезагрузки', async ({ browser, page, asRole }) => {
    await asRole('owner')
    const shot = await freshShot(page, '01.03')

    const second = await browser.newContext()
    await signIn(second, 'director')
    const other = await second.newPage()
    await other.goto('/')
    const ready = other.getByText(/\d+:\d{2} из \d+:\d{2}/).first()
    await expect(ready).toBeVisible()
    const before = await ready.textContent()

    await api(page, 'PATCH', `/shots/${shot.id}`, { status: 'done' })
    await expect(ready).not.toHaveText(before!, { timeout: 2500 })

    await api(page, 'PATCH', `/shots/${shot.id}`, { status: 'not_started' })
    await expect(ready).toHaveText(before!, { timeout: 2500 })
    await second.close()
  })

  test('плитка «Просрочено» ведёт в список просроченных задач', async ({ page, asRole }) => {
    await asRole('owner')
    const tasks = await api<TaskRef[]>(page, 'GET', '/tasks')
    const late = tasks.find((t) => t.status === 'not_started')!
    const fine = tasks.find((t) => t.id !== late.id && t.status === 'not_started' && (t.due_date === null || t.due_date > '2030-01-01'))
      ?? tasks.find((t) => t.id !== late.id && t.status === 'done')!
    await api(page, 'PATCH', `/tasks/${late.id}`, { due_date: '2020-01-01' })

    await page.goto('/')
    await mountAllTiles(page)
    await page.getByRole('link', { name: /Просрочено/ }).click()
    await expect(page).toHaveURL(/\/tasks\?overdue=1/)
    await expect(page.getByRole('status').filter({ hasText: 'Просроченные' })).toBeVisible()
    await expect(page.getByText(late.code, { exact: true })).toBeVisible()
    await expect(page.getByText(fine.code, { exact: true })).toHaveCount(0)

    await page.getByRole('button', { name: 'Сбросить фильтр' }).click()
    await expect(page).toHaveURL(/\/tasks$/)
    await expect(page.getByText(fine.code, { exact: true })).toBeVisible()
  })

  test('«Ассеты без шотов» ведёт в список без CH-01, но с глашатаем CH-06', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/')
    await mountAllTiles(page)
    await page.getByRole('link', { name: /Ассеты без шотов/ }).click()
    await expect(page).toHaveURL(/\/assets\?orphans=1/)
    await expect(page.getByText('CH-06', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('CH-01', { exact: true })).toHaveCount(0)
  })

  test('гость видит числа, но не ленту действий', async ({ page, asRole }) => {
    await asRole('guest')
    await page.goto('/')
    await mountAllTiles(page)
    await expect(page.getByText('Лента — часть журнала, гостю она не показывается')).toBeVisible()
  })

  test('плитки под сгибом строятся при подходе к ним и сразу все — по Tab', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/')
    await expect(page.getByText(/\d+:\d{2} из \d+:\d{2}/).first()).toBeVisible()
    const placeholder = page.locator('section[aria-label="Мои задачи"]')
    await expect(placeholder).toHaveCount(1) // ещё не построена: до неё далеко
    await page.keyboard.press('Tab')
    await expect(placeholder).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Мои задачи' })).toBeVisible()
  })

  test('в сгорании есть линия факта и честный прогноз при нулевом темпе', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/')
    await mountAllTiles(page)
    await expect(page.getByText('идеальная линия до внутреннего срока')).toBeVisible()
    await expect(page.getByText(/осталось \d+:\d{2}/)).toBeVisible()
  })
})
