import { api, expect, freshShot, test, type ShotRef } from './fixtures'

const shotRow = (page: import('@playwright/test').Page, code: string) => page.locator(`[data-shot="${code}"]`)

test.describe('шот-лист', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('69 шотов сгруппированы по сценам с таймкодами', async ({ page }) => {
    await page.goto('/shots')
    await expect(page.locator('[data-shot]')).toHaveCount(69)
    await expect(page.getByText('Сцена 1 · Два зеркала · 0:00–0:25')).toBeVisible()
    await expect(page.getByText('69 шотов · 360 сек')).toBeVisible()
  })

  test('список открывается быстрее секунды', async ({ page }) => {
    await page.goto('/shots')
    const ms = await page.evaluate(async () => {
      const t = performance.now()
      await fetch('/api/shots', { credentials: 'same-origin' }).then((r) => r.json())
      return performance.now() - t
    })
    expect(ms).toBeLessThan(1000)
    await expect(page.locator('[data-shot]')).toHaveCount(69)
  })

  test('статус меняется в один выбор, виден сразу и сохраняется', async ({ page }) => {
    const shot = await freshShot(page, '01.04')
    await page.goto('/shots')
    const row = shotRow(page, '01.04')
    await row.getByRole('button', { name: /Статус: Не начато/ }).click()
    await page.getByRole('menuitem', { name: 'В работе' }).click()
    await expect(row.getByRole('button', { name: /Статус: В работе/ })).toBeVisible() // цвет и подпись сразу
    await page.reload()
    await expect(shotRow(page, '01.04').getByRole('button', { name: /Статус: В работе/ })).toBeVisible()
    const journal = await api<{ items: { action: string; diff: Record<string, unknown> }[] }>(page, 'GET', `/activity?entity_type=shot&entity_id=${shot.id}`)
    expect(journal.items[0]).toMatchObject({ action: 'status', diff: { status: ['not_started', 'in_progress'] } })
  })

  test('цвета статусов — из токенов Excel-трекера', async ({ page }) => {
    await freshShot(page, '01.05')
    await page.goto('/shots')
    const dot = shotRow(page, '01.05').getByRole('button', { name: /Статус: Не начато/ }).locator('span > span').first()
    await expect(dot).toHaveCSS('background-color', 'rgb(124, 133, 151)') // серый «Не начато» из токена статуса
  })

  test('описание правится прямо в таблице', async ({ page, isMobile }) => {
    test.skip(!!isMobile, 'инлайн-правка таблицы — раскладка ПК; на телефоне правка в карточке')
    const shot = await freshShot(page, '01.06')
    const original = shot.description
    await page.goto('/shots')
    await shotRow(page, '01.06').getByRole('button', { name: /Описание кадра 01.06/ }).click()
    const field = shotRow(page, '01.06').getByRole('textbox', { name: /Описание кадра 01.06/ })
    await field.fill('Новое описание из теста')
    await field.press('Control+Enter')
    await expect(shotRow(page, '01.06').getByText('Новое описание из теста')).toBeVisible()
    await page.reload()
    await expect(shotRow(page, '01.06').getByText('Новое описание из теста')).toBeVisible()
    await api(page, 'PATCH', `/shots/${shot.id}`, { description: original })
  })

  test('групповая смена статуса выбранных строк', async ({ page, isMobile }) => {
    test.skip(!!isMobile, 'групповые операции — таблица на ПК')
    const shots = await Promise.all(['02.01', '02.02', '02.03'].map((c) => freshShot(page, c)))
    await page.goto('/shots')
    for (const s of shots) await shotRow(page, s.code).getByRole('checkbox').check()
    await expect(page.getByText('Выбрано: 3')).toBeVisible()
    await page.getByRole('button', { name: 'Сменить статус: Готово' }).click()
    for (const s of shots) await expect(shotRow(page, s.code).getByRole('button', { name: /Статус: Готово/ })).toBeVisible()
    for (const s of shots) await api(page, 'PATCH', `/shots/${s.id}`, { status: 'not_started' })
  })

  test('карточка шота открывается по ссылке и закрывается', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '01.02')
    await page.goto(`/shots?shot=${shot.id}`)
    const card = isMobile ? page.getByRole('dialog') : page.getByRole('complementary')
    await expect(card.getByText('01.02').first()).toBeVisible()
    await expect(card.getByText('Описание кадра')).toBeVisible()
    await expect(card.getByText('Дубли')).toBeVisible()
    await expect(card.getByText('Ассеты в кадре')).toBeVisible()
    await card.getByRole('button', { name: 'Закрыть' }).click()
    await expect(page).not.toHaveURL(/shot=/)
  })

  test('перетаскивание шота меняет порядок и сохраняется', async ({ page, isMobile }) => {
    test.skip(!!isMobile, 'перетаскивание касанием проверяется вручную: нужен долгий тап')
    const scene = (await api<{ id: number; number: number }[]>(page, 'GET', '/scenes')).find((s) => s.number === 4)!
    const codes = async () => (await api<ShotRef[]>(page, 'GET', `/shots?scene_id=${scene.id}`)).map((s) => s.code)
    const before = await codes()
    await page.goto('/shots')
    const handle = shotRow(page, before[0]).getByRole('button', { name: /Перетащить/ })
    const target = shotRow(page, before[2])
    await handle.scrollIntoViewIfNeeded() // строка может быть за пределами экрана: мышь туда не дотянется
    const from = (await handle.boundingBox())!
    const to = (await target.boundingBox())!
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(from.x + 4, from.y + 30, { steps: 5 })
    await page.mouse.move(from.x + 4, to.y + to.height - 4, { steps: 12 })
    await page.mouse.up()
    await expect.poll(codes).toEqual([before[1], before[2], before[0], ...before.slice(3)])
    // вернуть как было
    const ids = (await api<ShotRef[]>(page, 'GET', '/shots?scene_id=' + scene.id)).sort((a, b) => before.indexOf(a.code) - before.indexOf(b.code)).map((s) => s.id)
    await api(page, 'POST', '/reorder', { entity_type: 'shot', scene_id: scene.id, ids })
  })

  test('поиск и фильтр по статусу сужают список', async ({ page, isMobile }) => {
    await freshShot(page, '03.03')
    await page.goto('/shots')
    if (isMobile) await page.getByRole('button', { name: /Фильтры/ }).click()
    await page.getByRole('searchbox', { name: /Поиск по ID/ }).fill('03.03')
    await expect(page.locator('[data-shot]')).toHaveCount(1)
    await page.getByRole('searchbox', { name: /Поиск по ID/ }).fill('')
    await page.getByRole('button', { name: 'Готово' }).first().click()
    await expect(page.getByText('Ничего не найдено')).toBeVisible()
  })
})

test.describe('сцены, ассеты, сетапы, звук, задачи', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('сцены в порядке трекера с таймкодами; страница сцены с шотами', async ({ page }) => {
    await page.goto('/scenes')
    await expect(page.locator('[data-scene]')).toHaveCount(12)
    await expect(page.getByText('Итого по плану 6:00 · по шотам 6:00')).toBeVisible()
    await page.getByRole('link', { name: /Блеф как политика/ }).click()
    await expect(page.getByRole('heading', { name: 'Блеф как политика', level: 1 })).toBeVisible()
    await expect(page.getByText('0:25–0:55').first()).toBeVisible()
    await expect(page.getByRole('link', { name: /Карточка шота: 02\.01/ })).toBeVisible()
  })

  test('ассет: у овцы четыре состояния, у глашатая нет шотов', async ({ page }) => {
    const assets = await api<{ id: number; code: string }[]>(page, 'GET', '/assets')
    const sheep = assets.find((a) => a.code === 'AN-01')!
    await page.goto(`/assets?asset=${sheep.id}`)
    const card = page.getByRole('complementary').or(page.getByRole('dialog'))
    for (const name of ['белая', 'в саже и краске', 'в оранжево-чёрных полосах', 'мокрая, краска смыта']) {
      await expect(card.getByRole('button', { name: /Название состояния/ }).filter({ hasText: name })).toBeVisible()
    }
    const herald = assets.find((a) => a.code === 'CH-06')!
    await page.goto(`/assets?asset=${herald.id}`)
    await expect(card.getByText('Нет ни в одном шоте')).toBeVisible()
  })

  test('сетапы: 13 строк со ссылками на шоты', async ({ page }) => {
    await page.goto('/setups')
    await expect(page.locator('[data-setup]')).toHaveCount(13)
    await expect(page.locator('[data-setup="1"]').getByRole('link', { name: '01.04' }).first()).toBeVisible()
  })

  test('звук: 23 пункта, фильтр по типу', async ({ page }) => {
    await page.goto('/sound')
    await expect(page.locator('[data-cue]')).toHaveCount(23)
    await page.getByRole('button', { name: 'Реплика' }).click()
    await expect(page.locator('[data-cue]')).toHaveCount(12)
    await expect(page.getByText('Ma lord, ma lord!').first()).toBeVisible()
  })

  test('задачи: 29, фильтр по блоку и скрытие готовых', async ({ page }) => {
    await page.goto('/tasks')
    await expect(page.locator('[data-task]')).toHaveCount(29)
    await page.getByLabel('Скрыть готовые').check()
    await expect(page.locator('[data-task]')).toHaveCount(28)
    await page.getByRole('combobox', { name: 'Блок', exact: true }).selectOption({ label: 'Конкурс' })
    await expect(page.locator('[data-task]')).toHaveCount(3)
  })

  test('новая задача создаётся с автором и появляется в списке', async ({ page }) => {
    await page.goto('/tasks')
    await page.getByRole('button', { name: 'Новая задача' }).click()
    await page.getByLabel('Что нужно сделать').fill('Проверить титры')
    await page.getByRole('button', { name: 'Создать' }).click()
    await expect(page.getByText('Проверить титры').first()).toBeVisible()
    const tasks = await api<{ id: number; title: string; created_by: number | null }[]>(page, 'GET', '/tasks')
    const made = tasks.find((t) => t.title === 'Проверить титры')!
    expect(made.created_by).not.toBeNull()
    await api(page, 'DELETE', `/tasks/${made.id}`)
  })
})

test.describe('комментарии и журнал', () => {
  test('комментарий к шоту виден в треде и в истории карточки', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    const shot = await freshShot(page, '05.01')
    await page.goto(`/shots?shot=${shot.id}`)
    const card = isMobile ? page.getByRole('dialog') : page.getByRole('complementary')
    await card.getByRole('textbox', { name: 'Написать комментарий…' }).fill('Нужен ракурс ниже')
    await card.getByRole('button', { name: 'Отправить' }).click()
    await expect(card.getByText('Нужен ракурс ниже')).toBeVisible()
    await expect(card.getByText('Артём').first()).toBeVisible()
    const comments = await api<{ id: number }[]>(page, 'GET', `/comments?entity_type=shot&entity_id=${shot.id}`)
    for (const c of comments) await api(page, 'DELETE', `/comments/${c.id}`)
  })

  test('журнал показывает смену статуса: кто, что, было → стало', async ({ page, asRole }) => {
    await asRole('owner')
    const shot = await freshShot(page, '05.02')
    await api(page, 'PATCH', `/shots/${shot.id}`, { status: 'review' })
    await page.goto('/journal')
    const entry = page.locator('[data-activity="status"]').filter({ hasText: 'шот 05.02' }).first()
    await expect(entry).toContainText('Артём')
    await expect(entry).toContainText('статус: Не начато → На проверке')
    await api(page, 'PATCH', `/shots/${shot.id}`, { status: 'not_started' })
  })
})

test.describe('роль «Команда»', () => {
  test('меняет статус чужого шота, но не его содержимое', async ({ page, asRole, isMobile }) => {
    await asRole('team')
    const shot = await freshShot(page, '06.01')
    await page.goto('/shots')
    if (!isMobile) {
      await expect(shotRow(page, '06.01').getByRole('button', { name: /Описание кадра 06.01/ })).toBeDisabled()
    }
    await shotRow(page, '06.01').getByRole('button', { name: /Статус: Не начато/ }).click()
    await page.getByRole('menuitem', { name: 'Готово' }).click()
    await expect(shotRow(page, '06.01').getByRole('button', { name: /Статус: Готово/ })).toBeVisible()
    const denied = await page.context().request.fetch(`/api/shots/${shot.id}`, { method: 'PATCH', data: { description: 'взлом' } })
    expect(denied.status()).toBe(403)
    await freshShot(page, '06.01')
  })

  test('гость видит шот-лист, но не меняет статус', async ({ page, asRole }) => {
    await asRole('guest')
    await page.goto('/shots')
    await expect(page.locator('[data-shot]')).toHaveCount(69)
    await expect(shotRow(page, '01.01').getByRole('button', { name: /Статус:/ })).toHaveCount(0)
  })
})
