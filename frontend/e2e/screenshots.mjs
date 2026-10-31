// Скриншоты ключевых экранов на ширине ПК (1440) и телефона (390). Запуск: npm run shots
import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'
import { seedDemo } from './demo.mjs'
import { BASE_URL, sessionCookie } from './session.mjs'

const out = process.argv[2] ?? 'screenshots'
fs.mkdirSync(out, { recursive: true })

const cookie = sessionCookie()
const demo = await seedDemo(cookie)
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
  await shoot(`${label}-scenes`, viewport, { url: '/scenes' }, { mobile })
  await shoot(`${label}-scene-detail`, viewport, { url: `/scenes/${demo.scene}`, fullPage: true }, { mobile })
  await shoot(`${label}-shots`, viewport, { url: '/shots' }, { mobile })
  await shoot(`${label}-shot-card`, viewport, { url: `/shots?shot=${demo.firstShot}` }, { mobile })
  await shoot(`${label}-assets`, viewport, { url: '/assets' }, { mobile })
  await shoot(`${label}-asset-card`, viewport, { url: `/assets?asset=${demo.sheep}` }, { mobile })
  await shoot(`${label}-setups`, viewport, { url: '/setups' }, { mobile })
  await shoot(`${label}-sound`, viewport, { url: '/sound' }, { mobile })
  await shoot(`${label}-tasks`, viewport, { url: '/tasks' }, { mobile })
  await shoot(`${label}-journal`, viewport, { url: '/journal' }, { mobile })
  await shoot(`${label}-brand`, viewport, { url: '/brand', fullPage: true }, { mobile })
}

await shoot('desktop-status-menu', desktop, {
  url: '/shots',
  act: (p) => p.locator('tr[data-shot="01.04"]').getByRole('button', { name: /Статус/ }).click(),
})
await shoot('desktop-viewer-video', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  act: async (p) => {
    await p.getByRole('button', { name: /Открыть: Два зеркала/ }).first().click()
    await p.waitForTimeout(600)
  },
})
await shoot('desktop-viewer-audio', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  act: async (p) => {
    await p.getByRole('button', { name: /Открыть: Скрип трубы/ }).first().click()
    await p.waitForTimeout(1200)
  },
})
await shoot('desktop-lens-tile', desktop, {
  url: `/shots?shot=${demo.firstShot}`,
  act: (p) => p.getByRole('button', { name: /Открыть: Референс пролива/ }).first().hover(),
})
await shoot('phone-bottom-sheet-more', phone, { url: '/', act: (p) => p.getByRole('button', { name: 'Ещё' }).click() }, { mobile: true })

await browser.close()
console.log('готово →', out)
