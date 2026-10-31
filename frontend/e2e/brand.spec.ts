import { expect, test } from './fixtures'

test.describe('бренд', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('тёмная тема по умолчанию, цвета и шрифты берутся из токенов', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    expect(bg).toBe('rgb(14, 20, 32)') // ink #0E1420
    const fonts = await page.evaluate(() => ({
      display: getComputedStyle(document.querySelector('h1')!).fontFamily,
      body: getComputedStyle(document.body).fontFamily,
    }))
    expect(fonts.display).toContain('Cormorant Garamond')
    expect(fonts.body).toContain('Manrope')
  })

  test('шрифты с кириллицей реально загружены', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await page.evaluate(() => document.fonts.ready)
    const loaded = await page.evaluate(() =>
      [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family).join(' '),
    )
    expect(loaded).toMatch(/Cormorant Garamond/)
    expect(loaded).toMatch(/Manrope/)
  })

  test('светлая тема переключается и запоминается', async ({ page, isMobile }) => {
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    await page.getByRole('button', { name: 'Светлая тема' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    expect(bg).toBe('rgb(243, 238, 225)')
  })

  test('в шапке отсчёт до официального срока подачи, дни и часы', async ({ page }) => {
    await page.goto('/')
    const timer = page.locator('header').getByRole('timer')
    await expect(timer).toBeVisible()
    await expect(timer).toHaveAttribute('aria-label', /До подачи: \d+ дн \d+ ч/)
  })

  test('в подвале бейдж конкурса', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('footer').getByText('Entry · 1 Billion AI Film Award 2027')).toBeVisible()
  })

  test('линза включает эффект «через трубу» по наведению и по касанию', async ({ page, isMobile }) => {
    await page.goto('/brand')
    const lens = page.getByRole('img', { name: 'Север и Юг' }).first()
    await expect(lens).toHaveAttribute('data-tube', 'false')
    if (isMobile) await lens.tap()
    else await lens.hover()
    await expect(lens).toHaveAttribute('data-tube', 'true')
    if (isMobile) {
      await lens.tap() // повторный тап выключает
      await expect(lens).toHaveAttribute('data-tube', 'false')
      await lens.tap()
      await expect(lens).toHaveAttribute('data-tube', 'true')
    }
    const filter = await lens.locator('img').evaluate((el) => getComputedStyle(el).filter)
    expect(filter).toContain('url(')
  })

  test('статусы как в Excel-трекере: «Вырезано» зачёркнуто', async ({ page }) => {
    await page.goto('/')
    for (const name of ['Не начато', 'В работе', 'На проверке', 'Доработать', 'Готово', 'Вырезано']) {
      await expect(page.getByText(name, { exact: true }).first()).toBeVisible()
    }
    await expect(page.getByText('Вырезано', { exact: true }).first()).toHaveCSS('text-decoration-line', 'line-through')
  })
})
