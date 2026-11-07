import { expect, test } from './fixtures'

const noHorizontalScroll = (page: import('@playwright/test').Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

test.describe('раскладки', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('ПК: левый сайдбар со всеми разделами, без нижней панели', async ({ page, isMobile }) => {
    test.skip(!!isMobile, 'только ПК')
    // Импорт-тесты заводят в общей базе другие проекты: у владельца сайта их стало несколько, а здесь проверяем
    // раскладку с одним проектом — ответ сессии подменяется.
    await page.route('**/api/session', (r) =>
      r.fulfill({
        json: {
          user: { id: 1, name: 'Артём', tg_username: 'artem', color: '#E8C979', role: 'owner', has_avatar: false, last_seen_at: null },
          is_superadmin: false,
          projects: [{ slug: 'brass-spyglass', title: 'Битва при кривом зеркале', title_en: 'The Brass Spyglass', role: 'owner', archived: false }],
          can_create_projects: false,
          pending_count: 0,
        },
      }),
    )
    await page.goto('/')
    const nav = page.getByRole('navigation', { name: 'The Brass Spyglass' }).first()
    await expect(nav.getByRole('link')).toHaveCount(16)
    await expect(page.getByRole('button', { name: 'Ещё' })).toBeHidden()
    expect(await noHorizontalScroll(page)).toBe(true)
  })

  test('телефон: нижняя панель из 5 пунктов, сайдбара нет', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'только телефон')
    await page.goto('/')
    const bar = page.getByRole('navigation', { name: 'The Brass Spyglass' }).last()
    await expect(bar.getByRole('link')).toHaveCount(4)
    await expect(bar.getByRole('button', { name: 'Ещё' })).toBeVisible()
    for (const name of ['Дашборд', 'Шоты', 'Медиа', 'Задачи']) {
      await expect(bar.getByRole('link', { name })).toBeVisible()
    }
    await expect(page.locator('aside')).toBeHidden()
    expect(await noHorizontalScroll(page)).toBe(true)
  })

  test('телефон: «Ещё» открывает остальные разделы и закрывается', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'только телефон')
    await page.goto('/')
    await page.getByRole('button', { name: 'Ещё' }).click()
    const sheet = page.getByRole('dialog', { name: 'Ещё' })
    await expect(sheet.getByRole('link', { name: 'Сцены' })).toBeVisible()
    await sheet.getByRole('link', { name: 'Ассеты' }).click()
    await expect(page).toHaveURL(/\/assets$/)
    await expect(sheet).toBeHidden()
    await expect(page.getByRole('heading', { name: 'Ассеты', level: 1 })).toBeVisible()
  })

  test('разделы следующих этапов — заглушки с номером этапа', async ({ page, isMobile }) => {
    test.skip(!!isMobile, 'на телефоне проверено через «Ещё»')
    await page.goto('/')
    await page.getByRole('link', { name: 'Корзина' }).click()
    await expect(page).toHaveURL(/\/trash$/)
    await expect(page.getByRole('heading', { name: 'Корзина' })).toBeVisible()
    await expect(page.getByText('Раздел появится на этапе 4')).toBeVisible()
  })

  test('неизвестный адрес — страница 404 с возвратом на дашборд', async ({ page }) => {
    await page.goto('/nowhere')
    await expect(page.getByRole('heading', { name: 'Такого раздела нет' })).toBeVisible()
    await page.getByRole('link', { name: 'На дашборд' }).click()
    await expect(page).toHaveURL(/\/p\/brass-spyglass\/?$/)
  })

  test('области касания элементов навигации не меньше 44 × 44 px', async ({ page, isMobile }) => {
    await page.goto('/')
    const nav = page.getByRole('navigation', { name: 'The Brass Spyglass' })
    const targets = isMobile ? nav.last().locator('a, button') : nav.first().getByRole('link')
    await expect(targets.first()).toBeVisible()
    const boxes = await targets.evaluateAll((els) =>
      els.map((e) => e.getBoundingClientRect()).map((r) => [r.width, r.height]),
    )
    expect(boxes.length).toBeGreaterThan(3)
    for (const [w, h] of boxes) {
      expect(w).toBeGreaterThanOrEqual(44)
      expect(h).toBeGreaterThanOrEqual(44)
    }
  })
})
