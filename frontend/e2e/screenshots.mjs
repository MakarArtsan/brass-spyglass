// Скриншоты ключевых экранов на ширине ПК (1440) и телефона (390). Запуск: npm run shots
import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'
import { BASE_URL, sessionCookie } from './session.mjs'

const out = process.argv[2] ?? 'screenshots'
fs.mkdirSync(out, { recursive: true })

const cookie = sessionCookie()
const browser = await chromium.launch()

async function shoot(name, viewport, setup, { mobile = false } = {}) {
  const ctx = await browser.newContext({ viewport, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: mobile ? 2 : 1 })
  if (setup.auth !== false) {
    await ctx.addCookies([{ name: 'bs_session', value: cookie, url: BASE_URL, httpOnly: true }])
  }
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.error('PAGE ERROR', name, e.message))
  page.on('console', (m) => m.type() === 'error' && console.error('CONSOLE', name, m.text()))
  await page.goto(BASE_URL + setup.url)
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => document.fonts.ready)
  if (setup.act) await setup.act(page)
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: setup.fullPage ?? false })
  await ctx.close()
}

const desktop = { width: 1440, height: 900 }
const phone = { width: 390, height: 844 }

for (const [label, viewport, mobile] of [['desktop', desktop, false], ['phone', phone, true]]) {
  await shoot(`${label}-login`, viewport, { url: '/login', auth: false }, { mobile })
  await shoot(`${label}-dashboard`, viewport, { url: '/' }, { mobile })
  await shoot(`${label}-team`, viewport, { url: '/team' }, { mobile })
  await shoot(`${label}-placeholder`, viewport, { url: '/shots' }, { mobile })
  await shoot(`${label}-brand`, viewport, { url: '/brand', fullPage: true }, { mobile })
  await shoot(`${label}-dashboard-light`, viewport, {
    url: '/',
    act: async (p) => {
      if (mobile) await p.getByRole('button', { name: 'Ещё' }).click()
      await p.getByRole('button', { name: /Светлая тема/ }).click()
      if (mobile) await p.getByRole('dialog').getByRole('button', { name: 'Закрыть' }).click()
    },
  }, { mobile })
}

await shoot('phone-more-sheet', phone, {
  url: '/',
  act: (p) => p.getByRole('button', { name: 'Ещё' }).click(),
}, { mobile: true })

await shoot('desktop-lens-tube', desktop, {
  url: '/brand',
  act: async (p) => {
    await p.getByRole('img', { name: 'Север и Юг' }).first().hover()
  },
})

await browser.close()
console.log('готово →', out)
