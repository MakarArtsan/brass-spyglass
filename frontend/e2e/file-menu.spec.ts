import { api, expect, freshShot, test, uniqueImage, uploadViaApi } from './fixtures'

interface Attached {
  attachment_id: number
  file: { id: number; original_name: string }
}

const filesOf = (page: import('@playwright/test').Page, shotId: number) =>
  api<Attached[]>(page, 'GET', `/files?entity_type=shot&entity_id=${shotId}`)

const cardOf = (page: import('@playwright/test').Page, isMobile: boolean | undefined) =>
  isMobile ? page.getByRole('dialog') : page.getByRole('complementary').last()

async function clear(page: import('@playwright/test').Page, shotId: number) {
  for (const a of await filesOf(page, shotId)) await api(page, 'DELETE', `/files/${a.file.id}`)
}

test.describe('меню файла: убрать с карточки и удалить', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('кнопка меню видна на фото и достаточно велика для пальца', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '08.02')
    await clear(page, shot.id)
    await uploadViaApi(page, uniqueImage(`menu-visible-${isMobile ? 'p' : 'd'}`), { entityType: 'shot', entityId: shot.id, purpose: 'reference' })
    await page.goto(`/shots?shot=${shot.id}`)
    const trigger = cardOf(page, isMobile).getByRole('button', { name: /Показать ещё: menu-visible/ })
    await expect(trigger).toBeVisible()
    const box = (await trigger.boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(44)
    expect(box.height).toBeGreaterThanOrEqual(44)
    // видимый кружок со своим фоном, а не прозрачный значок поверх фото
    const background = await trigger.locator('span').first().evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(background).not.toBe('rgba(0, 0, 0, 0)')
    expect(background).not.toBe('transparent')
    await clear(page, shot.id)
  })

  test('«Убрать с карточки»: плитка исчезает, файл остаётся в медиатеке', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '08.03')
    await clear(page, shot.id)
    const tag = `detach-${isMobile ? 'p' : 'd'}`
    const { file } = await uploadViaApi(page, uniqueImage(tag), { entityType: 'shot', entityId: shot.id, purpose: 'reference' })
    await page.goto(`/shots?shot=${shot.id}`)
    const card = cardOf(page, isMobile)
    await card.getByRole('button', { name: new RegExp(`Показать ещё: ${tag}`) }).click()
    await page.getByRole('menuitem', { name: /Убрать с карточки/ }).click()
    await expect(card.getByRole('button', { name: new RegExp(`Открыть: ${tag}`) })).toHaveCount(0)
    await expect(page.getByText('Файл убран с карточки, он остался в медиатеке')).toBeVisible()
    expect((await filesOf(page, shot.id)).length).toBe(0)
    expect((await api<{ id: number }>(page, 'GET', `/files/${file.id}`)).id).toBe(file.id) // сам файл жив
    await api(page, 'DELETE', `/files/${file.id}`)
  })

  test('«Удалить файл»: окно предупреждает, плитка исчезает, файл пропадает совсем', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '08.04')
    await clear(page, shot.id)
    const tag = `remove-${isMobile ? 'p' : 'd'}`
    const { file } = await uploadViaApi(page, uniqueImage(tag), { entityType: 'shot', entityId: shot.id, purpose: 'reference' })
    await page.goto(`/shots?shot=${shot.id}`)
    const card = cardOf(page, isMobile)
    const messages: string[] = []
    page.once('dialog', async (dialog) => {
      messages.push(dialog.message())
      await dialog.accept()
    })
    await card.getByRole('button', { name: new RegExp(`Показать ещё: ${tag}`) }).click()
    await page.getByRole('menuitem', { name: /Удалить файл/ }).click()
    await expect(card.getByRole('button', { name: new RegExp(`Открыть: ${tag}`) })).toHaveCount(0)
    expect(messages[0]).toContain(tag)
    expect(messages[0]).toContain('Убрать с карточки') // подсказка, как не удалять лишнего
    await expect(page.getByText('Файл удалён', { exact: true })).toBeVisible()
    const gone = await page.context().request.get(`/api/files/${file.id}`)
    expect(gone.status()).toBe(404)
  })

  test('отказ в окне подтверждения ничего не удаляет', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '08.05')
    await clear(page, shot.id)
    const tag = `keep-${isMobile ? 'p' : 'd'}`
    await uploadViaApi(page, uniqueImage(tag), { entityType: 'shot', entityId: shot.id, purpose: 'reference' })
    await page.goto(`/shots?shot=${shot.id}`)
    page.once('dialog', (dialog) => dialog.dismiss())
    await cardOf(page, isMobile).getByRole('button', { name: new RegExp(`Показать ещё: ${tag}`) }).click()
    await page.getByRole('menuitem', { name: /Удалить файл/ }).click()
    await expect(cardOf(page, isMobile).getByRole('button', { name: new RegExp(`Открыть: ${tag}`) })).toBeVisible()
    await clear(page, shot.id)
  })
})
