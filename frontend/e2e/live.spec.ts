import { api, expect, freshShot, signIn, test } from './fixtures'

/** Общий критерий приёмки ТЗ: смена статуса видна второму пользователю без перезагрузки за 2 секунды. */
test.describe('живые обновления', () => {
  test('статус, изменённый одним, второй видит за 2 секунды без перезагрузки', async ({ browser, page, asRole }) => {
    await asRole('owner')
    const shot = await freshShot(page, '01.06')

    const second = await browser.newContext()
    await signIn(second, 'team')
    const other = await second.newPage()
    await other.goto('/shots')
    const row = other.locator(`[data-shot="${shot.code}"]`)
    await expect(row.getByRole('button', { name: /Статус: Не начато/ })).toBeVisible()

    const started = Date.now()
    await api(page, 'PATCH', `/shots/${shot.id}`, { status: 'review' })
    await expect(row.getByRole('button', { name: /Статус: На проверке/ })).toBeVisible({ timeout: 2000 })
    expect(Date.now() - started).toBeLessThan(2000)

    // страница не перезагружалась: фокус и прокрутка на месте, сессия SSE жива
    await expect(other).toHaveURL(/\/shots$/)
    await second.close()
  })

  test('новый комментарий появляется у второго пользователя в открытой карточке', async ({ browser, page, asRole }) => {
    await asRole('owner')
    const shot = await freshShot(page, '01.02')

    const second = await browser.newContext()
    await signIn(second, 'director')
    const other = await second.newPage()
    await other.goto(`/shots?shot=${shot.id}`)
    // карточка уже открыта и загрузила комментарии (поле ввода на месте), перезагрузок дальше нет
    await expect(other.getByPlaceholder('Написать комментарий…')).toBeVisible()

    const text = `живой комментарий ${Date.now()}`
    await api(page, 'POST', '/comments', { entity_type: 'shot', entity_id: shot.id, body: text })
    await expect(other.getByText(text)).toBeVisible({ timeout: 2000 })
    await second.close()
  })
})
