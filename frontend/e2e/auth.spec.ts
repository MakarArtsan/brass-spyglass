import { expect, test } from './fixtures'

const OWNER = { id: 1, name: 'Артём', tg_username: 'artem', color: '#E8C979', role: 'owner', has_avatar: false, last_seen_at: null }

test.describe('вход', () => {
  test('без сессии ведёт на экран входа с бейджем конкурса', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Вход в штаб' })).toBeVisible()
    await expect(page.getByText('Entry · 1 Billion AI Film Award 2027')).toBeVisible()
  })

  test('пока Telegram не настроен, кнопка заблокирована и объясняет почему', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('button', { name: /Войти через Telegram/ })).toBeDisabled()
    await expect(page.getByRole('alert')).toContainText('пока не настроен')
  })

  test('бот подтвердил вход: сайт ждёт по SSE, забирает сессию и открывает дашборд', async ({ page }) => {
    let claimed = false
    await page.route('https://t.me/**', (route) => route.fulfill({ body: 'ok' }))
    await page.route('**/api/auth/config', (r) => r.fulfill({ json: { login_available: true, bot_username: 'brass_bot' } }))
    await page.route('**/api/auth/login-token', (r) =>
      r.fulfill({ json: { token: 'tok123', bot_url: 'https://t.me/brass_bot?start=tok123', expires_in: 300 } }),
    )
    await page.route('**/api/auth/login-token/tok123/events', (r) =>
      r.fulfill({ contentType: 'text/event-stream', body: 'retry: 60000\n\nevent: confirmed\ndata: {}\n\n' }),
    )
    await page.route('**/api/auth/login-token/tok123/claim', (r) => {
      claimed = true
      return r.fulfill({ json: OWNER })
    })
    await page.route('**/api/project', (r) => r.fulfill({ status: 404, json: { detail: 'нет' } }))
    // /api/me отвечает 401 до того, как сайт забрал сессию, и данными — после.
    await page.route('**/api/me', (r) =>
      claimed
        ? r.fulfill({
            json: {
              user: OWNER,
              abilities: { upload: true, export: true, journal: true, manage_users: true, restore: true },
            },
          })
        : r.fulfill({ status: 401, json: { detail: 'Требуется вход' } }),
    )

    await page.goto('/login')
    await page.getByRole('button', { name: /Войти через Telegram/ }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { name: /Добро пожаловать на борт, Артём/ })).toBeVisible()
  })

  test('устаревшая ссылка показывает понятную ошибку', async ({ page }) => {
    await page.route('https://t.me/**', (route) => route.fulfill({ body: 'ok' }))
    await page.route('**/api/auth/config', (r) => r.fulfill({ json: { login_available: true, bot_username: 'brass_bot' } }))
    await page.route('**/api/auth/login-token', (r) =>
      r.fulfill({ json: { token: 'old', bot_url: 'https://t.me/brass_bot?start=old', expires_in: 300 } }),
    )
    await page.route('**/api/auth/login-token/old/events', (r) =>
      r.fulfill({ contentType: 'text/event-stream', body: 'event: expired\ndata: {}\n\n' }),
    )
    await page.goto('/login')
    await page.getByRole('button', { name: /Войти через Telegram/ }).click()
    await expect(page.getByRole('alert')).toContainText('устарела')
  })

  test('выход возвращает на экран входа', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    await page.getByRole('button', { name: 'Выйти' }).click()
    await expect(page).toHaveURL(/\/login$/)
    await page.goto('/')
    await expect(page).toHaveURL(/\/login$/)
  })
})
