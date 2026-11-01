import { api, expect, freshShot, test, uniqueVideo } from './fixtures'

interface Attached {
  file: { id: number; original_name: string; version_no: number; versions_count: number }
}

const filesOf = (page: import('@playwright/test').Page, shotId: number) =>
  api<Attached[]>(page, 'GET', `/files?entity_type=shot&entity_id=${shotId}`)

const cardOf = (page: import('@playwright/test').Page, isMobile: boolean | undefined) =>
  isMobile ? page.getByRole('dialog') : page.getByRole('complementary')

test.describe('версии и финальный файл', () => {
  test.setTimeout(90_000) // две загрузки видео и их обработка ffmpeg
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('новая версия, откат и отметка «Финал» — на карточке шота', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '07.02')
    for (const a of await filesOf(page, shot.id)) await api(page, 'DELETE', `/files/${a.file.id}`)
    await page.goto(`/shots?shot=${shot.id}`)
    const card = cardOf(page, isMobile)

    await card.getByLabel('Выбрать файлы').first().setInputFiles(uniqueVideo('take-one'))
    const first = card.getByRole('button', { name: /Открыть: take-one\.mp4/ })
    await expect(first).toBeVisible({ timeout: 20_000 })

    // отметка «Финал» — на первой версии
    await card.getByRole('button', { name: /Показать ещё: take-one\.mp4/ }).click()
    await page.getByRole('menuitem', { name: 'Сделать финальным' }).click()
    await expect(card.locator('span:text-is("Финал")')).toBeVisible()

    // новая версия: загрузка из окна версий, привязка к карточке переходит сама
    await card.getByRole('button', { name: /Показать ещё: take-one\.mp4/ }).click()
    await page.getByRole('menuitem', { name: /Версии/ }).click()
    const dialog = page.getByRole('dialog', { name: 'Версии файла' })
    await expect(dialog.getByText('текущая')).toBeVisible()
    await dialog.locator('input[type=file]').setInputFiles(uniqueVideo('take-two'))
    await expect.poll(async () => (await filesOf(page, shot.id))[0]?.file.version_no).toBe(2)
    expect(await filesOf(page, shot.id)).toHaveLength(1) // на карточке одна запись — текущая версия
    // окно версий закрылось само после загрузки
    await expect(dialog).toBeHidden()
    await expect(card.getByRole('button', { name: /Открыть: take-two\.mp4/ })).toBeVisible()
    await expect(card.locator('span:text-is("Финал")')).toBeVisible() // финал перешёл на v2
    expect((await api<{ final: { version_no: number } }[]>(page, 'GET', '/shots')).find((s) => (s as unknown as { id: number }).id === shot.id)?.final.version_no).toBe(2)

    // откат одной кнопкой
    await card.getByRole('button', { name: /Показать ещё: take-two\.mp4/ }).click()
    await page.getByRole('menuitem', { name: /Версии/ }).click()
    const history = page.getByRole('dialog', { name: 'Версии файла' })
    await expect(history.getByRole('listitem')).toHaveCount(2)
    await history.getByRole('button', { name: 'Вернуть эту версию' }).click()
    await expect.poll(async () => (await filesOf(page, shot.id))[0]?.file.version_no).toBe(1)
    await history.getByRole('button', { name: 'Закрыть' }).click()
    await expect(card.getByRole('button', { name: /Открыть: take-one\.mp4/ })).toBeVisible()

    for (const a of await filesOf(page, shot.id)) await api(page, 'DELETE', `/files/${a.file.id}`)
  })

  test('гость видит историю версий, но не может загрузить новую и откатить', async ({ page, asRole, isMobile }) => {
    const shot = await freshShot(page, '07.03')
    for (const a of await filesOf(page, shot.id)) await api(page, 'DELETE', `/files/${a.file.id}`)
    await page.goto(`/shots?shot=${shot.id}`)
    const card = cardOf(page, isMobile)
    await card.getByLabel('Выбрать файлы').first().setInputFiles(uniqueVideo('guest-view'))
    await expect(card.getByRole('button', { name: /Открыть: guest-view\.mp4/ })).toBeVisible()

    await asRole('guest')
    await page.goto(`/shots?shot=${shot.id}`)
    await expect(card.getByRole('button', { name: /Открыть: guest-view\.mp4/ })).toBeVisible()
    await card.getByRole('button', { name: /Показать ещё: guest-view\.mp4/ }).click()
    await expect(page.getByRole('menuitem', { name: 'Сделать финальным' })).toHaveCount(0)
    await page.getByRole('menuitem', { name: /Версии/ }).click() // историю смотреть можно
    const dialog = page.getByRole('dialog', { name: 'Версии файла' })
    await expect(dialog.getByText('текущая')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Загрузить новую версию' })).toHaveCount(0)
  })
})
