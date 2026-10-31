import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { api, expect, freshShot, sampleMedia, test, uniqueImage } from './fixtures'

interface Attached {
  attachment_id: number
  purpose: string
  file: { id: number; original_name: string; size_bytes: number; processing: boolean; uploaded_by: { name: string } | null; kind: string; urls: Record<string, string> }
}

const filesOf = (page: import('@playwright/test').Page, shotId: number) =>
  api<Attached[]>(page, 'GET', `/files?entity_type=shot&entity_id=${shotId}`)

const cardOf = (page: import('@playwright/test').Page, isMobile: boolean | undefined) =>
  isMobile ? page.getByRole('dialog') : page.getByRole('complementary')

async function clearFiles(page: import('@playwright/test').Page, shotId: number) {
  for (const a of await filesOf(page, shotId)) await api(page, 'DELETE', `/files/${a.file.id}`)
}

test.describe('загрузка файлов', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('кнопка «Добавить файлы»: плитка, автор, превью, прогресс', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '07.01')
    await clearFiles(page, shot.id)
    await page.goto(`/shots?shot=${shot.id}`)
    const card = cardOf(page, isMobile)
    const media = sampleMedia()
    await card.getByLabel('Выбрать файлы').first().setInputFiles(media.photo)
    await expect(card.getByRole('button', { name: /Открыть: photo\.png/ })).toBeVisible()
    await expect(card.getByText('Артём').first()).toBeVisible() // автор на каждом файле
    await expect.poll(async () => (await filesOf(page, shot.id))[0]?.file.processing).toBe(false)
    const [attached] = await filesOf(page, shot.id)
    expect(attached.file.uploaded_by?.name).toBe('Артём')
    expect(attached.file.urls.thumb).toBeTruthy()
    await clearFiles(page, shot.id)
  })

  test('перетаскивание файла с рабочего стола на строку шота', async ({ page, isMobile }) => {
    test.skip(!!isMobile, 'drag-and-drop с рабочего стола — только ПК')
    const shot = await freshShot(page, '07.02')
    await clearFiles(page, shot.id)
    await page.goto('/shots')
    const file = fs.readFileSync(sampleMedia().photo)
    const dataTransfer = await page.evaluateHandle(
      ({ bytes }) => {
        const dt = new DataTransfer()
        dt.items.add(new File([new Uint8Array(bytes)], 'dropped.png', { type: 'image/png' }))
        return dt
      },
      { bytes: [...file] },
    )
    const row = page.locator('[data-shot="07.02"]')
    await row.dispatchEvent('dragenter', { dataTransfer })
    await row.dispatchEvent('dragover', { dataTransfer })
    await expect(row).toHaveAttribute('data-drop-active', 'true') // подсветка зоны, куда упадёт файл
    await expect(page.getByText('Бросьте файлы', { exact: true })).toBeVisible()
    await row.dispatchEvent('drop', { dataTransfer })
    await expect.poll(async () => (await filesOf(page, shot.id)).map((a) => a.file.original_name)).toEqual(['dropped.png'])
    await clearFiles(page, shot.id)
  })

  test('бросок мимо зоны ничего не загружает и подсказывает, куда бросать', async ({ page, isMobile }) => {
    test.skip(!!isMobile, 'только ПК')
    await page.goto('/shots')
    const dataTransfer = await page.evaluateHandle(() => {
      const dt = new DataTransfer()
      dt.items.add(new File([new Uint8Array([1, 2, 3])], 'x.png', { type: 'image/png' }))
      return dt
    })
    await page.locator('h1').dispatchEvent('dragenter', { dataTransfer })
    await page.locator('h1').dispatchEvent('drop', { dataTransfer })
    await expect(page.getByText('Бросьте файл на строку шота, карточку или состояние ассета')).toBeVisible()
  })

  test('обрыв сети посреди загрузки: докачка с того же места, файл целый', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '07.03')
    await clearFiles(page, shot.id)
    // 20 МБ: три куска по 8 МБ. Второй кусок «обрываем» один раз.
    const big = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bs-e2e-')), 'big.webm')
    const bytes = Buffer.alloc(20 * 1024 * 1024)
    for (let i = 0; i < bytes.length; i += 4096) bytes.writeUInt32LE((i * 2654435761) >>> 0, i)
    fs.writeFileSync(big, bytes)
    let cut = 0
    await page.route('**/api/uploads/*', (route) => {
      const request = route.request()
      if (request.method() === 'PATCH' && request.headers()['upload-offset'] === String(8 * 1024 * 1024) && cut === 0) {
        cut += 1
        return route.abort('connectionreset')
      }
      return route.continue()
    })
    await page.goto(`/shots?shot=${shot.id}`)
    await cardOf(page, isMobile).getByLabel('Выбрать файлы').first().setInputFiles(big)
    await expect.poll(async () => (await filesOf(page, shot.id))[0]?.file.size_bytes, { timeout: 60_000 }).toBe(bytes.length)
    expect(cut).toBe(1) // обрыв действительно был
    await clearFiles(page, shot.id)
  })

  test('тот же файл второй раз: предупреждение о дубле, «всё равно добавить» без повторной отправки', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '07.04')
    await clearFiles(page, shot.id)
    const image = uniqueImage('duplicate-check')
    await page.goto(`/shots?shot=${shot.id}`)
    const input = cardOf(page, isMobile).getByLabel('Выбрать файлы').first()
    await input.setInputFiles(image)
    await expect.poll(async () => (await filesOf(page, shot.id)).length).toBe(1)
    await input.setInputFiles(image)
    const dialog = page.getByRole('dialog', { name: 'Такой файл уже есть' })
    await expect(dialog).toContainText('Этот файл уже добавлял Артём')
    await expect(dialog).toContainText('шот 07.04')
    await dialog.getByRole('button', { name: 'Всё равно добавить' }).click()
    await expect.poll(async () => (await filesOf(page, shot.id)).length).toBe(2)
    await clearFiles(page, shot.id)
  })

  test('неподдерживаемый формат отклоняется сразу', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '07.05')
    await page.goto(`/shots?shot=${shot.id}`)
    const exe = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bs-e2e-')), 'virus.exe')
    fs.writeFileSync(exe, 'MZ')
    await cardOf(page, isMobile).getByLabel('Выбрать файлы').first().setInputFiles(exe)
    await expect(page.getByText('virus.exe: Формат не поддерживается')).toBeVisible()
    expect(await filesOf(page, shot.id)).toHaveLength(0)
  })

  test('гость не видит кнопок загрузки', async ({ page, asRole }) => {
    await asRole('guest')
    const shot = await freshShot(page, '07.06')
    await page.goto(`/shots?shot=${shot.id}`)
    await expect(page.getByRole('button', { name: 'Добавить файлы' })).toHaveCount(0)
  })
})

test.describe('просмотр медиа на сайте', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('фото, видео и аудио открываются в окне просмотра, стрелки переключают файлы', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '08.01')
    await clearFiles(page, shot.id)
    const media = sampleMedia()
    await page.goto(`/shots?shot=${shot.id}`)
    const card = cardOf(page, isMobile)
    await card.getByLabel('Выбрать файлы').first().setInputFiles([media.photo, media.video, media.audio])
    await expect.poll(async () => (await filesOf(page, shot.id)).filter((a) => !a.file.processing).length, { timeout: 40_000 }).toBe(3)

    await card.getByRole('button', { name: /Открыть: photo\.png/ }).click()
    const viewer = page.getByRole('dialog').last()
    await expect(viewer.getByRole('img', { name: 'photo.png' })).toBeVisible()
    await expect(viewer.getByText(/Добавил Артём/)).toBeVisible() // кто, когда и откуда
    await page.keyboard.press('ArrowRight')
    await expect(viewer.getByText('clip.mp4').first()).toBeVisible()
    await expect(viewer.locator('video')).toBeVisible()
    await page.keyboard.press('ArrowRight')
    await expect(viewer.getByText('tone.wav').first()).toBeVisible()
    await expect(viewer.getByLabel('Звуковая дорожка')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(viewer).toBeHidden()
    await clearFiles(page, shot.id)
  })

  test('видеоплеер: играет, шагает по кадрам, меняет скорость', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '08.02')
    await clearFiles(page, shot.id)
    await page.goto(`/shots?shot=${shot.id}`)
    await cardOf(page, isMobile).getByLabel('Выбрать файлы').first().setInputFiles(sampleMedia().video)
    await expect.poll(async () => (await filesOf(page, shot.id))[0]?.file.processing, { timeout: 30_000 }).toBe(false)
    await cardOf(page, isMobile).getByRole('button', { name: /Открыть: clip\.mp4/ }).click()
    const viewer = page.getByRole('dialog').last()
    const video = viewer.locator('video')
    await expect(video).toBeVisible()
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1)

    await viewer.getByRole('button', { name: 'Играть' }).click()
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(0)
    await viewer.getByRole('button', { name: 'Пауза' }).click()

    const before = await video.evaluate((v: HTMLVideoElement) => v.currentTime)
    await viewer.getByRole('button', { name: /Кадр вперёд/ }).click()
    const after = await video.evaluate((v: HTMLVideoElement) => v.currentTime)
    expect(after - before).toBeCloseTo(1 / 24, 2) // ровно один кадр при 24 fps

    await viewer.getByLabel('Скорость').selectOption('0.25')
    expect(await video.evaluate((v: HTMLVideoElement) => v.playbackRate)).toBe(0.25)
    await clearFiles(page, shot.id)
  })

  test('Range-запрос к видео отдаёт 206 — перемотка работает', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '08.03')
    await clearFiles(page, shot.id)
    await page.goto(`/shots?shot=${shot.id}`)
    await cardOf(page, isMobile).getByLabel('Выбрать файлы').first().setInputFiles(sampleMedia().video)
    await expect.poll(async () => (await filesOf(page, shot.id))[0]?.file.processing, { timeout: 30_000 }).toBe(false)
    const [attached] = await filesOf(page, shot.id)
    const url = attached.file.urls.play
    const partial = await page.context().request.get(url, { headers: { Range: 'bytes=0-99' } })
    expect(partial.status()).toBe(206)
    expect((await partial.body()).length).toBe(100)
    expect(partial.headers()['content-range']).toMatch(/^bytes 0-99\//)
    // без сессии ссылка не работает
    const anonymous = await page.context().browser()!.newContext({ baseURL: page.url() })
    expect((await anonymous.request.get(new URL(url, page.url()).toString())).status()).toBe(401)
    await anonymous.close()
    await clearFiles(page, shot.id)
  })
})
