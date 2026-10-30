import { expect, test } from './fixtures'

test('дашборд показывает данные проекта из базы', async ({ page, asRole }) => {
  await asRole('owner')
  await page.goto('/')
  await expect(page.getByText('24 fps')).toBeVisible()
  await expect(page.getByText('1920 × 1080')).toBeVisible()
  await expect(page.getByText('5:00–7:00').first()).toBeVisible()
  await expect(page.getByText('20 ноября 2026 г. · по Дубаю')).toBeVisible()
  await expect(page.getByText('18 ноября 2026 г.')).toBeVisible()
})
