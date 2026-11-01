import { api, expect, freshShot, signIn, test, uniqueImage, uploadViaApi } from './fixtures'

test.describe('медиатека', () => {
  test('показывает файлы, фильтрует по типу, «без привязки» и поиску', async ({ page, asRole }) => {
    await asRole('owner')
    const tag = `lib${Date.now()}`
    const shot = await freshShot(page, '01.01')
    await uploadViaApi(page, uniqueImage(`${tag}-attached`), { entityType: 'shot', entityId: shot.id })
    await uploadViaApi(page, uniqueImage(`${tag}-free`))

    await page.goto('/media')
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-attached`) })).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-free`) })).toBeVisible()

    await page.getByRole('button', { name: 'Без привязки' }).click()
    await expect(page).toHaveURL(/unattached=1/)
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-free`) })).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-attached`) })).toHaveCount(0)

    await page.getByRole('button', { name: 'Видео' }).click()
    await expect(page.getByText('По этим условиям файлов нет')).toBeVisible()
    await page.getByRole('button', { name: 'Сбросить фильтры' }).click()

    await page.getByRole('searchbox', { name: 'Поиск файлов' }).fill(`${tag}-attached`)
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-attached`) })).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-free`) })).toHaveCount(0)
  })

  test('фильтр по автору из адреса показывает файлы только этого человека', async ({ browser, page, asRole }) => {
    await asRole('owner')
    const tag = `auth${Date.now()}`
    await uploadViaApi(page, uniqueImage(`${tag}-owner`))

    const second = await browser.newContext()
    await signIn(second, 'director')
    const other = await second.newPage()
    await uploadViaApi(other, uniqueImage(`${tag}-director`))
    const directorId = (await api<{ user: { id: number } }>(other, 'GET', '/me')).user.id
    await second.close()

    await page.goto(`/media?author=${directorId}`)
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-director`) })).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(`Открыть: ${tag}-owner`) })).toHaveCount(0)
  })

  test('ссылка добавляется карточкой с адресом сайта, внутренний адрес отклоняется понятным текстом', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/media')
    await page.getByRole('button', { name: 'Добавить ссылку' }).click()

    await page.getByLabel('Адрес').fill('http://127.0.0.1:8765/api/me')
    await page.getByRole('button', { name: 'Добавить', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('внутреннюю сеть')

    await page.getByLabel('Адрес').fill(`https://example.com/e2e-${Date.now()}`)
    await page.getByRole('button', { name: 'Добавить', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: 'Ссылки', exact: true }).click()
    await expect(page.getByRole('button', { name: /Открыть: example\.com|Открыть: .*e2e/ }).first()).toBeVisible()
  })

  test('файл из медиатеки привязывается к карточке без повторной загрузки', async ({ page, asRole }) => {
    await asRole('owner')
    const tag = `pick${Date.now()}`
    const shot = await freshShot(page, '01.04')
    const { file } = await uploadViaApi(page, uniqueImage(tag))

    await page.goto(`/shots?shot=${shot.id}`)
    await page.getByRole('button', { name: 'Из медиатеки' }).first().click()
    await page.getByRole('searchbox', { name: 'Поиск файлов' }).fill(tag)
    await page.getByRole('button', { name: new RegExp(`Выбрать: ${tag}`) }).click()
    await page.getByRole('button', { name: 'Привязать: 1' }).click()
    // на телефоне сама карточка — тоже диалог (нижний лист), поэтому проверяем именно окно выбора
    await expect(page.getByRole('dialog', { name: 'Файлы из медиатеки' })).toHaveCount(0)

    const attached = await api<{ file: { id: number } }[]>(page, 'GET', `/files?entity_type=shot&entity_id=${shot.id}`)
    expect(attached.map((a) => a.file.id)).toContain(file.id)
    const library = await api<{ total: number }>(page, 'GET', `/library?unattached=1&q=${tag}`)
    expect(library.total).toBe(0) // тот же файл, заново не загружался
  })

  test('гость видит медиатеку, но не кнопку добавления ссылки', async ({ page, asRole }) => {
    await asRole('guest')
    await page.goto('/media')
    await expect(page.getByRole('heading', { name: 'Медиатека' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Добавить ссылку' })).toHaveCount(0)
  })
})
