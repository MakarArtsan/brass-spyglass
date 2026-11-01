import { expect, test } from './fixtures'

// Каждый раздел: адрес и название в навигации.
const SECTIONS: [string, string][] = [
  ['/', 'Дашборд'],
  ['/scenes', 'Сцены'],
  ['/shots', 'Шот-лист'],
  ['/animatic', 'Аниматик'],
  ['/assets', 'Ассеты'],
  ['/media', 'Медиатека'],
  ['/setups', 'Сетапы и пэйоффы'],
  ['/sound', 'Звук и субтитры'],
  ['/tasks', 'Задачи'],
  ['/export', 'Экспорт'],
  ['/journal', 'Журнал'],
  ['/team', 'Команда'],
  ['/telegram', 'Telegram'],
  ['/trash', 'Корзина'],
]

test.describe('справка «i» у каждого раздела', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  for (const [path, label] of SECTIONS) {
    test(`${label}: кнопка «i» объясняет, зачем раздел и что в нём можно`, async ({ page }) => {
      await page.goto(path)
      const button = page.getByRole('button', { name: `О разделе «${label}»` })
      await expect(button).toBeVisible()
      const box = (await button.boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(44) // область касания по ТЗ
      expect(box.height).toBeGreaterThanOrEqual(44)

      await button.click()
      const dialog = page.getByRole('dialog', { name: `Раздел «${label}»` })
      await expect(dialog).toBeVisible()
      await expect(dialog.getByText('Зачем он нужен')).toBeVisible()
      await expect(dialog.getByText('Что здесь можно')).toBeVisible()
      expect(await dialog.getByRole('listitem').count()).toBeGreaterThanOrEqual(1)

      await dialog.getByRole('button', { name: 'Понятно' }).click()
      await expect(dialog).toBeHidden()
    })
  }

  test('закрывается клавишей Esc, на странице остаётся один заголовок', async ({ page }) => {
    await page.goto('/shots')
    await page.getByRole('button', { name: 'О разделе «Шот-лист»' }).click()
    const dialog = page.getByRole('dialog', { name: 'Раздел «Шот-лист»' })
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(page.getByRole('heading', { name: 'Шот-лист', level: 1 })).toHaveCount(1)
  })

  test('на телефоне окно помещается в экран и его содержимое читается', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'только телефон')
    await page.goto('/export')
    await page.getByRole('button', { name: 'О разделе «Экспорт»' }).click()
    const dialog = page.getByRole('dialog', { name: 'Раздел «Экспорт»' })
    const box = (await dialog.boundingBox())!
    const viewport = page.viewportSize()!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height)
  })

  test('гость видит справку тоже', async ({ page, asRole }) => {
    await asRole('guest')
    await page.goto('/media')
    await expect(page.getByRole('button', { name: 'О разделе «Медиатека»' })).toBeVisible()
  })
})
