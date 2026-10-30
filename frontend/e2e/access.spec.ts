import { expect, test } from './fixtures'

test.describe('роли в интерфейсе', () => {
  test('гость не видит журнал и экспорт, прямая ссылка на журнал ведёт на дашборд', async ({ page, asRole, isMobile }) => {
    await asRole('guest')
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    const scope = isMobile ? page.getByRole('dialog') : page.locator('aside')
    await expect(scope.getByRole('link', { name: 'Журнал' })).toHaveCount(0)
    await expect(scope.getByRole('link', { name: 'Экспорт' })).toHaveCount(0)
    await expect(scope.getByRole('link', { name: 'Команда' })).toHaveCount(1)
    await page.goto('/journal')
    await expect(page).toHaveURL(/\/$/)
  })

  test('роль «Команда» видит журнал и экспорт', async ({ page, asRole, isMobile }) => {
    await asRole('team')
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    const scope = isMobile ? page.getByRole('dialog') : page.locator('aside')
    await expect(scope.getByRole('link', { name: 'Журнал' })).toBeVisible()
    await expect(scope.getByRole('link', { name: 'Экспорт' })).toBeVisible()
  })

  test('экран «Команда» показывает участников с ролями', async ({ page, asRole }) => {
    await asRole('director')
    await page.goto('/team')
    await expect(page.getByRole('heading', { name: 'Команда' })).toBeVisible()
    await expect(page.locator('main').getByText('Режиссёр', { exact: true })).toBeVisible()
    await expect(page.locator('main').getByText('@dina', { exact: true })).toBeVisible()
  })

  test('API без сессии закрыт, health открыт без секретов', async ({ request }) => {
    expect((await request.get('/api/me')).status()).toBe(401)
    expect((await request.get('/api/project')).status()).toBe(401)
    const health = await request.get('/api/health')
    expect(health.ok()).toBe(true)
    expect(JSON.stringify(await health.json())).not.toContain('e2e-secret')
  })
})
