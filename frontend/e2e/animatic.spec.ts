import { api, expect, freshShot, sampleMedia, test, uploadViaApi } from './fixtures'

test.describe('аниматик', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('таймлайн: 12 сцен, шоты по порядку, дорожки звука, хронометраж 6:00', async ({ page }) => {
    await page.goto('/animatic')
    await expect(page.getByRole('heading', { name: 'Аниматик' })).toBeVisible()
    await expect(page.getByText('Хронометраж по шотам: 6:00')).toBeVisible()
    await expect(page.getByRole('link', { name: /Открыть шот/ })).toHaveCount(69)
    await expect(page.getByText('A1 · реплики')).toBeVisible()
    await expect(page.getByText('A3 · музыка')).toBeVisible()
    // шот открывается по клику
    await page.getByRole('link', { name: /Открыть шот 01\.01/ }).click()
    await expect(page).toHaveURL(/\/shots\?shot=\d+/)
  })

  test('«Смотреть фильм»: без файлов идут карточки с описанием, можно листать и закрыть', async ({ page }) => {
    await page.goto('/animatic')
    await page.getByRole('button', { name: 'Смотреть фильм' }).click()
    const player = page.getByRole('dialog', { name: 'Смотреть фильм' })
    await expect(player.getByText('Фрагмент 1 из 69')).toBeVisible()
    await expect(player.getByText('Файла пока нет: карточка с описанием на время шота')).toBeVisible()
    await player.getByRole('button', { name: 'Дальше' }).click()
    await expect(player.getByText('Фрагмент 2 из 69')).toBeVisible()
    await player.getByRole('button', { name: 'Назад' }).click()
    await expect(player.getByText('Фрагмент 1 из 69')).toBeVisible()
    await player.getByRole('button', { name: 'Пауза' }).click()
    await expect(player.getByRole('button', { name: 'Играть' })).toBeVisible()
    await player.getByRole('button', { name: 'Закрыть просмотр' }).click()
    await expect(player).toBeHidden()
  })

  test('готовый финальный файл шота играет вместо карточки', async ({ page }) => {
    const shots = await api<{ id: number; code: string }[]>(page, 'GET', '/shots')
    const first = shots.sort((a, b) => a.code.localeCompare(b.code))[0]
    await freshShot(page, first.code)
    const { file } = await uploadViaApi(page, sampleMedia().video, { entityType: 'shot', entityId: first.id, purpose: 'take' })
    await api(page, 'PUT', `/shots/${first.id}/final`, { file_id: file.id })
    try {
      await page.goto('/animatic')
      await expect(page.getByText('Готовых файлов в просмотре: 1 из 69')).toBeVisible()
      await page.getByRole('button', { name: 'Смотреть фильм' }).click()
      const player = page.getByRole('dialog', { name: 'Смотреть фильм' })
      await expect(player.locator('video')).toBeVisible()
      await expect(player.locator('video')).toHaveAttribute('src', /\/api\/files\/\d+\/(original|proxy)/)
    } finally {
      await api(page, 'PUT', `/shots/${first.id}/final`, { file_id: null })
      await api(page, 'DELETE', `/files/${file.id}`)
    }
  })

  test('гость тоже смотрит аниматик', async ({ page, asRole }) => {
    await asRole('guest')
    await page.goto('/animatic')
    await expect(page.getByRole('button', { name: 'Смотреть фильм' })).toBeEnabled()
  })
})
