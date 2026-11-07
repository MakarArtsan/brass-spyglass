import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { BASE_URL } from './session.mjs'
import { api, expect, test, uploadViaApi } from './fixtures'

// Имена файлов латинские: в окружении без UTF-8 браузер не получает файлы с кириллицей в имени от
// Playwright (кириллические имена в архиве проверяет pytest).
// Настоящий бэкенд: фото загружаются, коллаж собирается сервером, скачиваются картинка и архив.
// Раскладку, ограничения и права подробно проверяет pytest; здесь — что человек видит и может нажать.

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bs-collage-'))

/** Уникальное фото нужного размера: случайный цвет → своя контрольная сумма, поэтому «дубль» не срабатывает
 * (база общая для всех прогонов и для обоих размеров экрана). */
function photo(tag: string, w = 640, h = 480): string {
  const color = randomBytes(3).readUIntBE(0, 3)
  const file = path.join(dir, `${tag}.jpg`)
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', `color=c=0x${color.toString(16).padStart(6, '0')}:size=${w}x${h}`, '-frames:v', '1', file])
  return file
}

/** Название с хвостом: коллажи прежних прогонов остаются в базе и не должны мешать поиску карточки. */
const unique = (title: string) => `${title} ${randomBytes(2).toString('hex')}`

const set = (page: Page, files: string[]) => page.locator('input[type=file]').setInputFiles(files)
const thumbs = (page: Page) => page.getByRole('list', { name: 'Выбранные фото' }).getByRole('listitem')
const names = async (page: Page) => (await thumbs(page).locator('p.truncate').allTextContents()).map((t) => t.trim())

interface Item {
  id: number
  title: string
  width: number
  height: number
  photos: number
  download_url: string
  zip_url: string
}

async function viaApi(page: Page, title: string, tags: string[]): Promise<Item> {
  const ids: number[] = []
  for (const tag of tags) ids.push((await uploadViaApi(page, photo(tag))).file.id)
  return api<Item>(page, 'POST', '/collages', { title, file_ids: ids })
}

const bytes = async (page: Page, url: string) => {
  const res = await page.context().request.get(`${BASE_URL}${url}`)
  return { res, body: await res.body() }
}

test.describe('коллажи', () => {
  test.setTimeout(90_000)
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('путь целиком: фото → название → сборка → карточка; скачивается картинка и архив фото', async ({ page }) => {
    await page.goto('/collages')
    await expect(page.getByRole('heading', { level: 1, name: 'Коллажи' })).toBeVisible()
    const build = page.getByRole('button', { name: 'Собрать коллаж' })
    await expect(build).toBeDisabled()

    await set(page, [photo('north-1', 800, 600), photo('north-2', 600, 900), photo('north-3', 1280, 720)])
    await expect(thumbs(page)).toHaveCount(3)
    await expect(page.getByText('Выбрано 3 из 10')).toBeVisible()
    await expect(build).toBeDisabled() // названия нет
    const title = unique('Одежда северян')
    await page.getByLabel('Название коллажа').fill(title)
    await expect(build).toBeEnabled()
    await build.click()

    const card = page.getByRole('listitem').filter({ hasText: title }).first()
    await expect(card).toBeVisible({ timeout: 60_000 })
    await expect(card).toContainText('3 фото')
    await expect(card).toContainText('3840×')
    await expect(thumbs(page)).toHaveCount(0) // форма очистилась
    await expect(page.getByLabel('Название коллажа')).toHaveValue('')

    const list = await api<Item[]>(page, 'GET', '/collages')
    const made = list.find((c) => c.title === title)!
    expect(made.photos).toBe(3)
    const image = await bytes(page, made.download_url)
    expect(image.res.headers()['content-type']).toBe('image/jpeg')
    expect(image.body.subarray(0, 3).toString('hex')).toBe('ffd8ff')
    expect(image.body.length).toBeGreaterThan(5_000)
    const zip = await bytes(page, made.zip_url)
    expect(zip.res.headers()['content-type']).toBe('application/zip')
    expect(zip.body.subarray(0, 2).toString()).toBe('PK')
    const text = zip.body.toString('latin1')
    for (const n of ['01_north-1.jpg', '02_north-2.jpg', '03_north-3.jpg']) expect(text).toContain(Buffer.from(n).toString('latin1'))
  })

  test('порядок меняется стрелками, лишнее убирается, крайние стрелки отключены', async ({ page }) => {
    await page.goto('/collages')
    await set(page, [photo('a'), photo('b'), photo('c'), photo('d')])
    expect(await names(page)).toEqual(['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg'])
    await expect(page.getByRole('button', { name: 'Сдвинуть «a.jpg» раньше' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Сдвинуть «d.jpg» позже' })).toBeDisabled()
    await page.getByRole('button', { name: 'Сдвинуть «c.jpg» раньше' }).click()
    expect(await names(page)).toEqual(['a.jpg', 'c.jpg', 'b.jpg', 'd.jpg'])
    await page.getByRole('button', { name: 'Убрать «a.jpg»' }).click()
    expect(await names(page)).toEqual(['c.jpg', 'b.jpg', 'd.jpg'])
    await expect(page.getByText('Выбрано 3 из 10')).toBeVisible()
  })

  test('больше десяти фото не берётся, не фото пропускается, одного фото мало', async ({ page }) => {
    await page.goto('/collages')
    await set(page, Array.from({ length: 11 }, (_, i) => photo(`m${i}`, 320, 240)))
    await expect(thumbs(page)).toHaveCount(10)
    await expect(page.getByText(/не больше 10 фото/)).toBeVisible()
    for (let i = 0; i < 9; i += 1) await page.getByRole('button', { name: /^Убрать/ }).first().click()
    await expect(thumbs(page)).toHaveCount(1)
    await expect(page.getByText('Нужно хотя бы 2 фото')).toBeVisible()
    await page.getByLabel('Название коллажа').fill('Одно фото')
    await expect(page.getByRole('button', { name: 'Собрать коллаж' })).toBeDisabled()

    const note = path.join(dir, 'note.txt')
    fs.writeFileSync(note, 'не картинка')
    await set(page, [note])
    await expect(page.getByText(/«note.txt» — не фото/)).toBeVisible()
    await expect(thumbs(page)).toHaveCount(1)
  })

  test('уже загруженное фото берётся готовое, а то же фото дважды в одном коллаже — понятная ошибка', async ({ page }) => {
    await page.goto('/collages')
    const shared = photo('shared')
    await set(page, [shared, photo('first')])
    const first = unique('Первый')
    const second = unique('Второй')
    await page.getByLabel('Название коллажа').fill(first)
    await page.getByRole('button', { name: 'Собрать коллаж' }).click()
    await expect(page.getByRole('listitem').filter({ hasText: first }).first()).toBeVisible({ timeout: 60_000 })

    await set(page, [shared, photo('second')]) // «общее» уже есть в проекте
    await page.getByLabel('Название коллажа').fill(second)
    await page.getByRole('button', { name: 'Собрать коллаж' }).click()
    await expect(page.getByRole('listitem').filter({ hasText: second }).first()).toBeVisible({ timeout: 60_000 })

    await set(page, [shared])
    await set(page, [shared])
    await page.getByLabel('Название коллажа').fill('Двойник')
    await page.getByRole('button', { name: 'Собрать коллаж' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'то же фото' })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('listitem').filter({ hasText: 'Двойник' })).toHaveCount(0)
  })

  test('карточка открывается крупно: видно, из каких фото собран коллаж', async ({ page }) => {
    const title = unique('Здания юга')
    const made = await viaApi(page, title, ['south-1', 'south-2', 'south-3'])
    await page.goto('/collages')
    await page.getByRole('button', { name: `Открыть коллаж «${title}»` }).click()
    const dialog = page.getByRole('dialog', { name: title })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Из каких фото собран' })).toBeVisible()
    await expect(dialog.getByRole('listitem')).toHaveCount(3)
    await expect(dialog.getByRole('link', { name: 'Скачать коллаж' })).toHaveAttribute('href', made.download_url)
    await expect(dialog.getByRole('link', { name: 'Скачать фото' })).toHaveAttribute('href', made.zip_url)
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
  })

  test('удаление спрашивает подтверждение; отмена ничего не удаляет', async ({ page }) => {
    const title = unique('Лишний коллаж')
    await viaApi(page, title, ['l-1', 'l-2'])
    await page.goto('/collages')
    const card = page.getByRole('listitem').filter({ hasText: title }).first()
    await card.getByRole('button', { name: `Удалить коллаж «${title}»` }).click()
    await card.getByRole('button', { name: 'Отмена' }).click()
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: `Удалить коллаж «${title}»` }).click()
    await card.getByRole('button', { name: 'Да, удалить' }).click()
    await expect(page.getByRole('listitem').filter({ hasText: title })).toHaveCount(0)
  })

  test('гость видит и скачивает, но не собирает; «Команда» не удаляет чужое', async ({ page, asRole }) => {
    const title = unique('Чужой коллаж')
    const made = await viaApi(page, title, ['x-1', 'x-2'])
    await asRole('team')
    await page.goto('/collages')
    const mine = page.getByRole('listitem').filter({ hasText: title }).first()
    await expect(mine).toBeVisible()
    await expect(mine.getByRole('button', { name: /^Удалить/ })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Собрать коллаж' })).toBeVisible() // собирать команда может

    await asRole('guest')
    await page.goto('/collages')
    await expect(page.getByText(/Собирать коллажи могут участники команды/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Собрать коллаж' })).toHaveCount(0)
    await expect(page.getByRole('listitem').filter({ hasText: title }).first()).toBeVisible()
    expect((await bytes(page, made.download_url)).res.status()).toBe(200)
  })

  test('раздел есть в меню; на телефоне ничего не уезжает вбок, цели касания не меньше 44 px', async ({ page, isMobile }) => {
    await viaApi(page, 'Для проверки', ['v-1', 'v-2'])
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    await page.getByRole('link', { name: 'Коллажи' }).first().click()
    await expect(page).toHaveURL(/\/collages$/)
    await set(page, [photo('t-1'), photo('t-2')])
    const targets: Locator[] = [
      page.getByRole('button', { name: 'Выбрать фото' }),
      page.getByRole('button', { name: 'Сдвинуть «t-2.jpg» раньше' }),
      page.getByRole('button', { name: 'Убрать «t-1.jpg»' }),
      page.getByRole('button', { name: 'Собрать коллаж' }),
      page.getByRole('link', { name: 'Скачать коллаж' }).first(),
      page.getByRole('link', { name: 'Скачать фото' }).first(),
      page.getByRole('button', { name: /^Удалить коллаж/ }).first(),
    ]
    for (const target of targets) {
      const box = await target.boundingBox()
      expect(box, 'элемент виден').not.toBeNull()
      expect(box!.height).toBeGreaterThanOrEqual(43.5)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  })

  test('справка «i» объясняет раздел', async ({ page }) => {
    await page.goto('/collages')
    await page.getByRole('button', { name: 'О разделе «Коллажи»' }).click()
    await expect(page.getByText('Собирает несколько фото в одну картинку-обзор')).toBeVisible()
  })
})
