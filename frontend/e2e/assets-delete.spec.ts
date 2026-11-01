import { api, expect, test } from './fixtures'

interface AssetRef {
  id: number
  code: string
}

const cardOf = (page: import('@playwright/test').Page, isMobile: boolean | undefined) =>
  isMobile ? page.getByRole('dialog') : page.getByRole('complementary').last()

async function createAsset(page: import('@playwright/test').Page, code: string, name: string): Promise<AssetRef> {
  return api<AssetRef>(page, 'POST', '/assets', { code, name, type: 'character' })
}

test.describe('удаление ассета', () => {
  test('владелец удаляет ошибочный ассет из его карточки: она закрывается, ассет пропадает из списка', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const asset = await createAsset(page, `ER-${isMobile ? 'P' : 'D'}1`, 'Ошибочный ассет')
    await page.goto(`/assets?asset=${asset.id}`)
    const card = cardOf(page, isMobile)
    await expect(card.getByRole('heading', { name: asset.code })).toBeVisible()

    const dialogs: string[] = []
    page.once('dialog', async (dialog) => {
      dialogs.push(dialog.message())
      await dialog.accept()
    })
    await card.getByRole('button', { name: 'Удалить ассет' }).click()

    expect(dialogs[0]).toContain(asset.code)
    expect(dialogs[0]).toContain('Файлы остаются в медиатеке') // человек видит, что произойдёт
    await expect(page).not.toHaveURL(/asset=/)
    await expect(page.getByText(`Ассет ${asset.code} удалён`)).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(asset.code) })).toHaveCount(0)
    expect((await api<AssetRef[]>(page, 'GET', '/assets')).some((a) => a.id === asset.id)).toBe(false)
  })

  test('отказ в окне подтверждения ничего не удаляет', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const asset = await createAsset(page, `ER-${isMobile ? 'P' : 'D'}2`, 'Оставить')
    await page.goto(`/assets?asset=${asset.id}`)
    page.once('dialog', (dialog) => dialog.dismiss())
    await cardOf(page, isMobile).getByRole('button', { name: 'Удалить ассет' }).click()
    await expect(page).toHaveURL(/asset=/)
    expect((await api<AssetRef[]>(page, 'GET', '/assets')).some((a) => a.id === asset.id)).toBe(true)
    await api(page, 'DELETE', `/assets/${asset.id}`)
  })

  test('«Команда» не видит кнопку на чужом ассете, гость не видит её нигде', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const asset = await createAsset(page, `ER-${isMobile ? 'P' : 'D'}3`, 'Чужой')
    await asRole('team')
    await page.goto(`/assets?asset=${asset.id}`)
    await expect(cardOf(page, isMobile).getByRole('heading', { name: asset.code })).toBeVisible()
    await expect(cardOf(page, isMobile).getByRole('button', { name: 'Удалить ассет' })).toHaveCount(0)
    await asRole('guest')
    await page.goto(`/assets?asset=${asset.id}`)
    await expect(cardOf(page, isMobile).getByRole('heading', { name: asset.code })).toBeVisible()
    await expect(cardOf(page, isMobile).getByRole('button', { name: 'Удалить ассет' })).toHaveCount(0)
    await asRole('owner')
    await api(page, 'DELETE', `/assets/${asset.id}`)
  })
})
