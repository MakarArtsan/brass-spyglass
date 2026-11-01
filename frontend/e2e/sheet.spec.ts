import { expect, test } from './fixtures'

/**
 * Карточка открывается поверх экрана, а не растягивается на всю страницу: иначе на телефоне её нельзя прокрутить
 * одним пальцем. Раньше анимация появления страницы оставляла у обёртки transform, и position: fixed считался
 * от высоты всей страницы. Проявлялось только при переходе внутри приложения (например, из аниматика).
 */
test.describe('карточка после перехода внутри приложения', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('занимает экран, а не высоту страницы, и прокручивается жестом одним пальцем', async ({ page, context, isMobile }) => {
    await page.goto('/animatic')
    await page.getByRole('link', { name: /Открыть шот 01\.01/ }).first().click()
    await expect(page).toHaveURL(/\/shots\?shot=\d+/)
    const panel = isMobile ? page.getByRole('dialog') : page.getByRole('complementary').last()
    await expect(panel).toBeVisible()
    await page.waitForTimeout(700) // анимация листа и страницы закончилась

    const viewport = page.viewportSize()!
    const box = (await panel.boundingBox())!
    expect(box.height).toBeLessThanOrEqual(viewport.height + 1)
    expect(Math.round(box.y)).toBe(0)
    // ни у одного предка нет transform: от него зависит position: fixed
    const transformed = await panel.evaluate((el) => {
      for (let node = el.parentElement; node && node !== document.documentElement; node = node.parentElement) {
        if (getComputedStyle(node).transform !== 'none') return node.className
      }
      return null
    })
    expect(transformed).toBeNull()

    if (!isMobile) return
    const scroller = panel.locator('div.overflow-y-auto').first()
    const metrics = await scroller.evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight }))
    expect(metrics.client).toBeLessThan(viewport.height) // область прокрутки ограничена экраном
    expect(metrics.scroll).toBeGreaterThan(metrics.client) // а содержимого в ней больше

    // настоящие касания (start → move → end): один палец, без второго
    const cdp = await context.newCDPSession(page)
    const x = viewport.width / 2
    const y = viewport.height * 0.75
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] })
    for (let i = 1; i <= 12; i++) {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y - (250 * i) / 12 }] })
      await page.waitForTimeout(16)
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBeGreaterThan(100)
  })
})

test.describe('низ карточки на телефоне', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('последний элемент карточки не прячется под нижней панелью навигации', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'нижняя панель только на телефоне')
    await page.goto('/shots?shot=1')
    const sheet = page.getByRole('dialog')
    await expect(sheet).toBeVisible()
    await page.waitForTimeout(700)
    const scroller = sheet.locator('div.overflow-y-auto').first()
    await scroller.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    await page.waitForTimeout(300)
    const covered = await page.evaluate(() => {
      const sc = document.querySelector('[role=dialog][aria-modal=true] div.overflow-y-auto')!
      const last = sc.lastElementChild!.lastElementChild ?? sc.lastElementChild!
      const r = last.getBoundingClientRect()
      const nav = document.querySelector('nav.fixed')!.getBoundingClientRect()
      return r.bottom > nav.top + 1 // нижний край последнего блока заходит на панель
    })
    expect(covered).toBe(false)
  })
})
