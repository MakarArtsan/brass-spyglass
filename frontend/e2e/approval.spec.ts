import type { Page } from '@playwright/test'
import { BASE_URL } from './session.mjs'
import { expect, test } from './fixtures'

// Подтверждение проекта: ответы /api/session, /project и /api/projects/* подменяются. Права на сервере
// (загрузка до подтверждения запрещена) покрывает pytest.

const USER = { id: 1, name: 'Артём', tg_username: 'artem', color: '#E8C979', role: 'owner', has_avatar: false, last_seen_at: null }
const FILM = { slug: 'brass-spyglass', title: 'Битва при кривом зеркале', title_en: 'The Brass Spyglass', role: 'owner', archived: false }
const WAITING = { slug: 'klip', title: 'Клип «Пролив»', title_en: 'Strait', role: 'owner', archived: false, pending: true }

async function mockSession(page: Page, extra: Record<string, unknown> = {}) {
  await page.route('**/api/session', (r) =>
    r.fulfill({ json: { user: USER, is_superadmin: false, projects: [FILM], can_create_projects: false, pending_count: 0, ...extra } }),
  )
}

/** Проект фильма отвечает как неподтверждённый, пока не нажали «Подтвердить» (тогда — как подтверждённый). */
async function mockProject(page: Page, state: { approved: boolean }) {
  await page.route('**/api/p/brass-spyglass/project', async (route) => {
    const real = await (await route.fetch()).json()
    await route.fulfill({ json: { ...real, approved: state.approved } })
  })
}

test.describe('подтверждение проекта', () => {
  test('команда видит плашку и не видит кнопок решения', async ({ page, asRole }) => {
    await asRole('team')
    await mockSession(page)
    await mockProject(page, { approved: false })
    await page.goto('/')
    const banner = page.getByRole('status').filter({ hasText: 'Проект ждёт подтверждения' })
    await expect(banner).toBeVisible()
    await expect(banner).toContainText('файлы загружать нельзя')
    await expect(page.getByRole('button', { name: 'Подтвердить' })).toHaveCount(0)
  })

  test('подтверждённый проект плашки не показывает', async ({ page, asRole }) => {
    await asRole('team')
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByText('Проект ждёт подтверждения')).toHaveCount(0)
  })

  test('владелец сайта подтверждает прямо из плашки', async ({ page, asRole }) => {
    await asRole('owner')
    const state = { approved: false }
    await mockSession(page, { is_superadmin: true })
    await mockProject(page, state)
    let posted = ''
    await page.route('**/api/projects/brass-spyglass/approve', (r) => {
      posted = r.request().url()
      state.approved = true
      return r.fulfill({ json: { slug: 'brass-spyglass', title: 'Битва', status: 'approve' } })
    })
    await page.goto('/')
    await expect(page.getByText('Вы владелец сайта: подтвердите проект')).toBeVisible()
    await page.getByRole('button', { name: 'Подтвердить' }).click()
    await expect(page.getByText('Проект ждёт подтверждения')).toHaveCount(0)
    expect(posted).toContain('/api/projects/brass-spyglass/approve')
  })

  test('отказ из плашки отправляет на общий экран', async ({ page, asRole }) => {
    await asRole('owner')
    await mockSession(page, { is_superadmin: true })
    await mockProject(page, { approved: false })
    let rejected = false
    await page.route('**/api/projects/brass-spyglass/reject', (r) => {
      rejected = true
      return r.fulfill({ json: { slug: 'brass-spyglass', title: 'Битва', status: 'reject' } })
    })
    await page.goto('/')
    await page.getByRole('button', { name: 'Отклонить' }).click()
    await expect.poll(() => rejected).toBe(true)
    await expect(page).toHaveURL(/\/p\/brass-spyglass\/?$|\/$/)
  })

  test('экран заявок: подтвердить и отклонить, очередь пустеет', async ({ page }) => {
    await mockSession(page, { is_superadmin: true, pending_count: 2 })
    let queue = [
      { slug: 'klip', title: 'Клип «Пролив»', title_en: 'Strait', created_at: '2026-11-05T05:00:00Z', owner_name: 'Лена', owner_username: 'lena' },
      { slug: 'doc', title: 'Документалка', title_en: 'Doc', created_at: '2026-11-05T06:00:00Z', owner_name: 'Игорь', owner_username: null },
    ]
    await page.route('**/api/projects/pending', (r) => r.fulfill({ json: queue }))
    await page.route('**/api/projects/*/approve', (r) => {
      const slug = r.request().url().split('/').slice(-2)[0]
      queue = queue.filter((q) => q.slug !== slug)
      return r.fulfill({ json: { slug, title: 'x', status: 'approve' } })
    })
    await page.route('**/api/projects/*/reject', (r) => {
      const slug = r.request().url().split('/').slice(-2)[0]
      queue = queue.filter((q) => q.slug !== slug)
      return r.fulfill({ json: { slug, title: 'x', status: 'reject' } })
    })
    await page.goto(`${BASE_URL}/requests`)
    await expect(page.getByRole('heading', { name: 'Заявки на проекты' })).toBeVisible()
    await expect(page.getByText('Подал(а) Лена (@lena)')).toBeVisible()
    await expect(page.getByText('Подал(а) Игорь')).toBeVisible()

    const first = page.getByRole('listitem').filter({ hasText: 'Клип «Пролив»' })
    await first.getByRole('button', { name: 'Подтвердить' }).click()
    await expect(page.getByText('Клип «Пролив»')).toHaveCount(0)
    const second = page.getByRole('listitem').filter({ hasText: 'Документалка' })
    await second.getByRole('button', { name: 'Отклонить' }).click()
    await expect(page.getByText('Новых заявок нет.')).toBeVisible()
  })

  test('экран заявок не для обычных людей', async ({ page }) => {
    await mockSession(page)
    await page.route('**/api/projects/pending', (r) => r.fulfill({ status: 403, json: { detail: 'Заявки видит и решает только владелец сайта' } }))
    await page.goto(`${BASE_URL}/requests`)
    await expect(page.getByText('Заявки решает только владелец сайта.')).toBeVisible()
  })

  test('без входа экран заявок ведёт на вход', async ({ page }) => {
    await page.goto(`${BASE_URL}/requests`)
    await expect(page).toHaveURL(/\/login$/)
  })

  test('в переключателе у владельца сайта счётчик заявок, у проекта — подпись «ждёт подтверждения»', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await mockSession(page, { is_superadmin: true, pending_count: 3, projects: [FILM, WAITING] })
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    const link = page.getByRole('link', { name: /Заявки на проекты/ }).filter({ visible: true })
    await expect(link).toContainText('3')
    const box = await link.boundingBox()
    expect(box!.height).toBeGreaterThanOrEqual(44)
    const select = page.getByLabel(/^Проект/).filter({ visible: true })
    await expect(select.locator('option', { hasText: 'ждёт подтверждения' })).toHaveCount(1)
  })

  test('без заявок ссылки на заявки нет', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await mockSession(page, { is_superadmin: true, pending_count: 0, projects: [FILM, WAITING] })
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    await expect(page.getByRole('link', { name: /Заявки на проекты/ })).toHaveCount(0)
  })
})
