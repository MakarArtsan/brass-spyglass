import { api, expect, freshShot, mountDashboardTiles, sampleMedia, test } from './fixtures'

const GIB = 1024 ** 3

test.describe('лимит диска', () => {
  test('загрузка, не помещающаяся в лимит, отклоняется с понятной причиной', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const shot = await freshShot(page, '07.06')
    await page.route((url) => url.pathname === '/api/uploads', (route) =>
      route.request().method() === 'POST'
        ? route.fulfill({
            status: 507,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'На диске не хватает места: свободно 0.1 ГБ из 5.0 ГБ, а нужно 1.00 ГБ.' }),
          })
        : route.continue(),
    )
    await page.goto(`/shots?shot=${shot.id}`)
    const card = isMobile ? page.getByRole('dialog') : page.getByRole('complementary')
    await card.getByLabel('Выбрать файлы').first().setInputFiles(sampleMedia().photo)
    await expect(page.getByText('photo.png', { exact: true })).toBeVisible()
    await expect(page.getByText(/На диске не хватает места: свободно 0\.1 ГБ/)).toBeVisible()
  })

  for (const [name, usedPct, warn, full, text] of [
    ['на 84% — предупреждение', 84, true, false, 'Диск заполнен больше чем на 80%'],
    ['на 100% — загрузка остановлена', 100, true, true, 'Диск заполнен: новые файлы не принимаются.'],
  ] as const) {
    test(`дашборд ${name}`, async ({ page, asRole }) => {
      await asRole('owner')
      const real = await api<{ media: { storage: Record<string, unknown> } }>(page, 'GET', '/dashboard')
      const fake = { ...real, media: { ...real.media, storage: { used_bytes: (5 * usedPct * GIB) / 100, limit_bytes: 5 * GIB, used_pct: usedPct, warn, full } } }
      await page.route((url) => url.pathname === '/api/dashboard', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(fake) }))
      await page.goto('/')
      await mountDashboardTiles(page)
      await expect(page.getByRole('alert').filter({ hasText: text })).toBeVisible()
      await expect(page.getByRole('progressbar', { name: 'Диск' })).toHaveAttribute('aria-valuenow', String(usedPct))
    })
  }

  test('до 80% предупреждения нет', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/')
    await mountDashboardTiles(page)
    await expect(page.getByRole('progressbar', { name: 'Диск' })).toBeVisible()
    await expect(page.getByText('Диск заполнен больше чем на 80%')).toHaveCount(0)
  })
})
