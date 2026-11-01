import type { Browser, Page } from '@playwright/test'
import { api, expect, freshShot, sampleMedia, signIn, test, uploadViaApi } from './fixtures'

/** Второй участник: отдельный контекст браузера со своей сессией. */
async function otherPerson(browser: Browser, role: 'director' | 'team') {
  const context = await browser.newContext()
  await signIn(context, role)
  const page = await context.newPage()
  await page.goto('/')
  return { context, page }
}

const bell = (page: Page) => page.getByRole('button', { name: /^Уведомления/ })

test.describe('уведомления на сайте', () => {
  test.beforeEach(async ({ asRole, page }) => {
    await asRole('owner')
    await page.goto('/')
    await api(page, 'POST', '/notifications/read-all')
    await page.reload()
  })

  test('комментарий коллеги: счётчик появляется без перезагрузки, клик ведёт в карточку', async ({ page, browser }) => {
    const shot = await freshShot(page, '07.04')
    await page.goto('/shots')
    await expect(bell(page)).toHaveAccessibleName('Уведомления')

    const dina = await otherPerson(browser, 'director')
    await api(dina.page, 'POST', '/comments', { entity_type: 'shot', entity_id: shot.id, body: 'давай сделаем персонажа чуть реальнее' })

    await expect(bell(page)).toHaveAccessibleName('Уведомления: новых 1', { timeout: 10_000 }) // по SSE, без перезагрузки
    await bell(page).click()
    const panel = page.getByRole('dialog', { name: 'Уведомления' })
    const row = panel.getByRole('button', { name: /Дина оставил\(а\) комментарий/ }).first() // новые — сверху
    await expect(row).toContainText('шот 07.04')
    await expect(row).toContainText('давай сделаем персонажа чуть реальнее')
    await row.click()

    await expect(page).toHaveURL(new RegExp(`/shots\\?shot=${shot.id}`))
    await expect(panel).toBeHidden()
    await expect(bell(page)).toHaveAccessibleName('Уведомления') // прочитано
    await dina.context.close()
  })

  test('файл на карточке и новая версия попадают в уведомления; автору своё действие не приходит', async ({ page, browser }) => {
    const shot = await freshShot(page, '07.05')
    const dina = await otherPerson(browser, 'director')
    await api(dina.page, 'POST', '/notifications/read-all') // чистый счётчик у автора до загрузки
    await uploadViaApi(dina.page, sampleMedia().photo, { entityType: 'shot', entityId: shot.id, purpose: 'reference' })
    await page.goto('/')
    await expect(bell(page)).toHaveAccessibleName('Уведомления: новых 1', { timeout: 10_000 })
    await bell(page).click()
    await expect(page.getByRole('dialog', { name: 'Уведомления' }).getByRole('button', { name: /Дина добавил\(а\) файл/ }).first()).toContainText('photo.png')
    // автор свою загрузку не видит
    await dina.page.reload()
    await expect(dina.page.getByRole('button', { name: /^Уведомления/ })).toHaveAccessibleName('Уведомления')
    for (const a of await api<{ file: { id: number } }[]>(dina.page, 'GET', `/files?entity_type=shot&entity_id=${shot.id}`)) {
      await api(dina.page, 'DELETE', `/files/${a.file.id}`)
    }
    await dina.context.close()
  })

  test('«Прочитать все» снимает счётчик, а список остаётся', async ({ page, browser }) => {
    const shot = await freshShot(page, '07.06')
    const petya = await otherPerson(browser, 'team')
    for (const body of ['первое', 'второе']) await api(petya.page, 'POST', '/comments', { entity_type: 'shot', entity_id: shot.id, body })
    await page.goto('/')
    await expect(bell(page)).toHaveAccessibleName(/Уведомления: новых \d+/, { timeout: 10_000 })
    await bell(page).click()
    const panel = page.getByRole('dialog', { name: 'Уведомления' })
    await expect(panel.getByRole('button', { name: /Петя оставил\(а\) комментарии \(2\)/ }).first()).toBeVisible() // серия склеена
    await panel.getByRole('button', { name: 'Прочитать все' }).click()
    await expect(panel.getByRole('button', { name: 'Прочитать все' })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: /Петя оставил/ }).first()).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(bell(page)).toHaveAccessibleName('Уведомления')
    await petya.context.close()
  })

  test('когда ничего нового, панель объясняет, что здесь будет', async ({ page }) => {
    await api(page, 'POST', '/notifications/read-all')
    await bell(page).click()
    const panel = page.getByRole('dialog', { name: 'Уведомления' })
    await expect(panel).toBeVisible()
    await expect(panel.getByRole('list', { name: 'Уведомления' }).or(panel.getByText('Пока ничего нового'))).toBeVisible()
  })

  test('гость тоже получает уведомления и может прочитать', async ({ page, asRole, browser }) => {
    const shot = await freshShot(page, '07.03')
    await asRole('guest')
    await page.goto('/')
    await api(page, 'POST', '/notifications/read-all')
    const petya = await otherPerson(browser, 'team')
    await api(petya.page, 'POST', '/comments', { entity_type: 'shot', entity_id: shot.id, body: 'для гостя' })
    await expect(bell(page)).toHaveAccessibleName('Уведомления: новых 1', { timeout: 10_000 })
    await petya.context.close()
  })
})
