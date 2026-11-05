import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Page } from '@playwright/test'
import { BASE_URL } from './session.mjs'
import { expect, test } from './fixtures'

// Настоящий бэкенд: тест заводит пустой проект владельцем сайта и проходит весь путь импорта на живых данных.
// Права, транзакцию и все правила проверки покрывает pytest; здесь — что человек видит и может нажать.

const here = path.dirname(fileURLToPath(import.meta.url))
const EXAMPLE = fs.readFileSync(path.resolve(here, '../../backend/app/scenario/example-brass-spyglass.json'), 'utf8')

let counter = 0

/** Новый пустой проект; возвращает адрес. Названия разные, чтобы тесты не мешали друг другу. */
async function emptyProject(page: Page): Promise<string> {
  counter += 1
  const res = await page.context().request.fetch(`${BASE_URL}/api/projects`, {
    method: 'POST',
    data: { title: `Импорт ${Date.now()} ${counter}`, title_en: `Import ${Date.now()}-${counter}` },
  })
  if (!res.ok()) throw new Error(`создание проекта: ${res.status()} ${await res.text()}`)
  return ((await res.json()) as { slug: string }).slug
}


const PASTE = 'Или вставьте ответ LLM целиком'

/** Вставка текста как это делает браузер: сразу целиком. `fill` в Playwright вставляет 46 КБ по кусочкам и
 * занимает секунд пятнадцать на любой textarea (проверено на пустой странице), а человек вставляет за миг. */
async function paste(page: Page, text: string) {
  await page.getByLabel(PASTE).evaluate((el, value) => {
    const area = el as HTMLTextAreaElement
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, value)
    area.dispatchEvent(new Event('input', { bubbles: true }))
  }, text)
}

const broken = () => {
  const data = JSON.parse(EXAMPLE) as { scenes: { shots: { asset_codes: string[] }[] }[] }
  data.scenes[0].shots[0].asset_codes.push('PR-77')
  return JSON.stringify(data)
}

test.describe('импорт сценария', () => {
  test.setTimeout(90_000)
  test.beforeEach(async ({ context, asRole }) => {
    await asRole('owner')
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE_URL }).catch(() => undefined)
  })

  test('путь целиком: файл → проверка → предпросмотр → исключить → создать', async ({ page }) => {
    const slug = await emptyProject(page)
    await page.goto(`/p/${slug}/import`)
    await expect(page.getByRole('heading', { level: 1, name: 'Импорт сценария' })).toBeVisible()

    // Шаг 1: промпт и пример скачиваются с адресов проекта
    await expect(page.getByRole('link', { name: 'Скачать import-prompt.md' })).toHaveAttribute('href', new RegExp(`/api/p/${slug}/import/prompt\\?language=en`))
    await page.getByLabel('Минимум, сек').fill('300')
    await page.getByLabel('Шот не длиннее, сек').fill('10')
    await expect(page.getByRole('link', { name: 'Скачать import-prompt.md' })).toHaveAttribute('href', /target_min_sec=300.*max_shot_sec=10|max_shot_sec=10.*target_min_sec=300/)
    const prompt = await page.context().request.get(`${BASE_URL}/api/p/${slug}/import/prompt?max_shot_sec=10`)
    expect(await prompt.text()).toContain('не длиннее 10 сек')

    // Шаг 2: файл и проверка
    await expect(page.getByRole('button', { name: 'Проверить' })).toBeDisabled()
    await page.locator('input[type=file]').setInputFiles({ name: 'project.json', mimeType: 'application/json', buffer: Buffer.from(EXAMPLE) })
    await expect(page.getByRole('list', { name: 'Загруженные файлы' })).toContainText('project.json')
    await page.getByRole('button', { name: 'Проверить' }).click()

    // Шаг 3: предпросмотр
    const preview = page.getByRole('region', { name: '3. Что получится' })
    await expect(preview).toBeVisible()
    const counters = preview.getByLabel('Что будет создано')
    await expect(counters).toContainText('12')
    await expect(counters).toContainText('69')
    await expect(counters).toContainText('17персонажей')
    await expect(counters).toContainText('14локаций')
    await expect(counters).toContainText('23ассетов')
    await expect(preview.getByRole('button', { name: 'Создать проект' })).toBeEnabled()

    // Полоса фильма: нажали сцену — видны её шоты
    await preview.getByRole('button', { name: /^Сцена 1:/ }).click()
    await expect(preview.getByText('01.01', { exact: true })).toBeVisible()

    // Исключить персонажа
    await preview.getByRole('tab', { name: /Персонажи/ }).click()
    const hero = preview.getByRole('checkbox', { name: /Не импортировать: Тигр|Не импортировать:/ }).first()
    const heroLabel = (await hero.getAttribute('aria-label')) ?? ''
    await hero.check()
    await expect(preview.getByText('Не будет создано: 1')).toBeVisible()

    await preview.getByRole('button', { name: 'Создать проект' }).click()
    await expect(page).toHaveURL(new RegExp(`/p/${slug}/?$`))
    await expect(page.getByText(/Создано: 12 сцен, 69 шотов/)).toBeVisible()

    // Данные настоящие: сцены и шоты на месте, исключённого ассета нет, автор — тот, кто импортировал
    const get = async <T>(url: string) => (await (await page.context().request.get(`${BASE_URL}/api/p/${slug}${url}`)).json()) as T
    expect((await get<unknown[]>('/scenes')).length).toBe(12)
    expect((await get<unknown[]>('/shots')).length).toBe(69)
    const assets = await get<{ name: string }[]>('/assets')
    expect(assets.length).toBe(53)
    expect(assets.map((a) => a.name)).not.toContain(heroLabel.replace('Не импортировать: ', ''))

    // Второй раз в тот же проект нельзя, а прошлый импорт виден в истории
    await page.goto(`/p/${slug}/import`)
    await expect(page.getByRole('heading', { name: 'Прошлые импорты' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Скачать исходник' })).toHaveAttribute('href', new RegExp(`/api/p/${slug}/import/runs/\\d+/source`))
    await page.locator('input[type=file]').setInputFiles({ name: 'project.json', mimeType: 'application/json', buffer: Buffer.from(EXAMPLE) })
    await page.getByRole('button', { name: 'Проверить' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'пустой проект' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Создать проект' })).toBeDisabled()
  })

  test('на дашборде пустого проекта есть ссылка на импорт, в проекте с данными её нет', async ({ page }) => {
    const slug = await emptyProject(page)
    await page.goto(`/p/${slug}/`)
    await expect(page.getByRole('heading', { name: 'Проект пока пустой' })).toBeVisible()
    await page.getByRole('link', { name: 'Импортировать сценарий' }).first().click()
    await expect(page).toHaveURL(new RegExp(`/p/${slug}/import$`))
    await page.goto('/')
    await expect(page.getByText('Готовность проекта').first()).toBeVisible() // плитки загрузились
    await expect(page.getByRole('heading', { name: 'Проект пока пустой' })).toHaveCount(0)
  })

  test('ошибки по-русски, с адресом, и кнопка «Скопировать ошибки для LLM»', async ({ page }) => {
    const slug = await emptyProject(page)
    await page.goto(`/p/${slug}/import`)
    await paste(page, `Конечно, вот файл:\n\`\`\`json\n${broken()}\n\`\`\``)
    await page.getByRole('button', { name: 'Проверить' }).click()
    const alert = page.getByRole('alert').filter({ hasText: 'проект пока не создать' })
    await expect(alert).toContainText('Сцена 1, шот 1: неизвестный ассет PR-77')
    await expect(page.getByRole('region', { name: '3. Что получится' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Создать проект' })).toHaveCount(0)

    await alert.getByRole('button', { name: 'Скопировать ошибки для LLM' }).click()
    await expect(page.getByText('Скопировано')).toBeVisible()
    const copied = await page.evaluate(() => navigator.clipboard.readText())
    expect(copied).toMatch(/^Исправь в JSON следующее:\n- Сцена 1, шот 1: неизвестный ассет PR-77/)
    expect(copied).toContain('Верни исправленный JSON целиком')
  })

  test('правка файла после ошибки: предпросмотр появляется, старый результат не висит', async ({ page }) => {
    const slug = await emptyProject(page)
    await page.goto(`/p/${slug}/import`)
    await paste(page, broken())
    await page.getByRole('button', { name: 'Проверить' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'проект пока не создать' })).toBeVisible()
    await paste(page, EXAMPLE)
    await expect(page.getByRole('alert').filter({ hasText: 'проект пока не создать' })).toHaveCount(0) // результат сброшен
    await page.getByRole('button', { name: 'Проверить' }).click()
    await expect(page.getByRole('region', { name: '3. Что получится' })).toBeVisible()
    await expect(page.getByText(/предупреждение — проект создать можно|предупреждений — проект создать можно/)).toBeVisible()
  })

  test('в проекте с данными проверка работает, а создать нельзя', async ({ page }) => {
    await page.goto('/import')
    await paste(page, EXAMPLE)
    await page.getByRole('button', { name: 'Проверить' }).click()
    const preview = page.getByRole('region', { name: '3. Что получится' })
    await expect(preview).toBeVisible()
    await expect(preview.getByRole('alert')).toContainText('пустой проект')
    await expect(preview.getByRole('button', { name: 'Создать проект' })).toBeDisabled()
  })

  test('команда и гость не видят раздел и уходят с его адреса', async ({ page, asRole }) => {
    for (const role of ['team', 'guest'] as const) {
      await asRole(role)
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await expect(page.getByRole('link', { name: 'Импорт сценария' })).toHaveCount(0)
      await page.goto('/import')
      await expect(page).not.toHaveURL(/\/import$/)
    }
  })

  test('режиссёр видит раздел в меню, у справки «i» есть текст', async ({ page, asRole }) => {
    await asRole('director')
    await page.goto('/import')
    await expect(page.getByRole('heading', { level: 1, name: 'Импорт сценария' })).toBeVisible()
    await page.getByRole('button', { name: 'О разделе «Импорт сценария»' }).click()
    await expect(page.getByText('Превращает сценарий в готовый проект')).toBeVisible()
  })

  test('цели касания не меньше 44 px и страница не уезжает вбок', async ({ page }) => {
    const slug = await emptyProject(page)
    await page.goto(`/p/${slug}/import`)
    await paste(page, EXAMPLE)
    await page.getByRole('button', { name: 'Проверить' }).click()
    const preview = page.getByRole('region', { name: '3. Что получится' })
    await expect(preview).toBeVisible()
    for (const target of [
      page.getByRole('link', { name: 'Скачать import-prompt.md' }),
      page.getByRole('button', { name: 'Проверить' }),
      preview.getByRole('button', { name: 'Создать проект' }),
      preview.getByRole('tab').first(),
      preview.getByRole('button', { name: /^Сцена 1:/ }),
      preview.getByRole('checkbox').first().locator('xpath=ancestor::label'),
    ]) {
      const box = await target.boundingBox()
      expect(box, 'элемент виден').not.toBeNull()
      expect(box!.height).toBeGreaterThanOrEqual(43.5)
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
