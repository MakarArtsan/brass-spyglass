import fs from 'node:fs'
import { api, compressibleImage, expect, freshShot, mountDashboardTiles, test, uploadViaApi } from './fixtures'

interface FileState {
  id: number
  size_bytes: number
  original_name: string
  compression: { state: 'done' | 'small_gain' | 'failed' | null; no_compress: boolean; original_size_bytes: number | null; can_restore: boolean }
}
interface Attached {
  file: { id: number }
}

type Page = import('@playwright/test').Page

const filesOf = (page: Page, shotId: number) => api<Attached[]>(page, 'GET', `/files?entity_type=shot&entity_id=${shotId}`)
const fileState = (page: Page, id: number) => api<FileState>(page, 'GET', `/files/${id}`)
const cardOf = (page: Page, isMobile: boolean | undefined) => (isMobile ? page.getByRole('dialog') : page.getByRole('complementary').last())

async function clear(page: Page, shotId: number) {
  for (const a of await filesOf(page, shotId)) await api(page, 'DELETE', `/files/${a.file.id}`)
}

/** Сжатие идёт фоновой задачей после превью: ждём итог. */
async function compressed(page: Page, id: number): Promise<FileState> {
  await expect.poll(async () => (await fileState(page, id)).compression.state, { timeout: 40_000 }).not.toBeNull()
  return fileState(page, id)
}

test.describe('сжатие картинок', () => {
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('итог сжатия в карточке файла и «Вернуть оригинал»', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '09.01')
    await clear(page, shot.id)
    const tag = `squeeze-${isMobile ? 'p' : 'd'}`
    const source = compressibleImage(tag)
    const originalSize = fs.statSync(source).size
    const { file } = await uploadViaApi(page, source, { entityType: 'shot', entityId: shot.id, purpose: 'reference' })

    const done = await compressed(page, file.id)
    expect(done.compression.state).toBe('done')
    expect(done.size_bytes).toBeLessThan(originalSize * 0.9)
    expect(done.compression.original_size_bytes).toBe(originalSize)
    expect(done.compression.can_restore).toBe(true)

    await page.goto(`/shots?shot=${shot.id}`)
    await cardOf(page, isMobile).getByRole('button', { name: new RegExp(`Открыть: ${tag}`) }).click()
    const note = page.getByTestId('compression-note')
    await expect(note).toContainText('→')
    await expect(note).toContainText(/−\d+%/)
    await expect(note).toContainText('оригинал хранится до')
    const restore = note.getByRole('button', { name: 'Вернуть оригинал' })
    const box = (await restore.boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(44)

    page.once('dialog', (dialog) => {
      expect(dialog.message()).toContain('повторно этот файл сжиматься не будет')
      void dialog.accept()
    })
    await restore.click()
    await expect(page.getByText('Оригинал возвращён')).toBeVisible()
    await expect(note).toContainText('без сжатия')
    await expect(note.getByRole('button', { name: 'Вернуть оригинал' })).toHaveCount(0)

    const back = await fileState(page, file.id)
    expect(back.size_bytes).toBe(originalSize) // оригинал бит в бит
    expect(back.compression).toMatchObject({ state: null, no_compress: true, can_restore: false })
    await clear(page, shot.id)
  })

  test('галочка «Без сжатия»: видна, крупная, файл остаётся оригиналом', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '09.02')
    await clear(page, shot.id)
    await page.goto(`/shots?shot=${shot.id}`)
    const card = cardOf(page, isMobile)
    // У каждой секции с файлами свои кнопки загрузки и своя галочка; состояние у них общее.
    const toggle = card.getByLabel('Без сжатия').first()
    await expect(toggle).toBeVisible()
    const row = (await toggle.locator('xpath=ancestor::label').boundingBox())!
    expect(row.height).toBeGreaterThanOrEqual(44)

    const tag = `master-${isMobile ? 'p' : 'd'}`
    const source = compressibleImage(tag)
    await toggle.check()
    await expect(card.getByLabel('Без сжатия').nth(1)).toBeChecked() // общее для всех кнопок загрузки
    await card.getByLabel('Выбрать файлы').first().setInputFiles(source)
    await expect(card.getByRole('button', { name: new RegExp(`Открыть: ${tag}`) })).toBeVisible()
    await expect.poll(async () => (await filesOf(page, shot.id)).length).toBe(1)
    const [attached] = await filesOf(page, shot.id)
    await expect.poll(async () => (await fileState(page, attached.file.id)).compression.no_compress).toBe(true)
    const state = await fileState(page, attached.file.id)
    expect(state.compression.state).toBeNull()
    expect(state.size_bytes).toBe(fs.statSync(source).size) // бит в бит
    await clear(page, shot.id)
  })

  test('плитка «Сэкономлено места сжатием» на дашборде', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '09.03')
    await clear(page, shot.id)
    const { file } = await uploadViaApi(page, compressibleImage(`tile-${isMobile ? 'p' : 'd'}`), { entityType: 'shot', entityId: shot.id, purpose: 'reference' })
    expect((await compressed(page, file.id)).compression.state).toBe('done')
    await page.goto('/')
    await mountDashboardTiles(page)
    await expect(page.getByRole('heading', { name: 'Сэкономлено места сжатием' })).toBeVisible()
    await expect(page.getByTestId('saved-bytes')).toBeVisible()
    await expect(page.getByTestId('saved-bytes')).not.toHaveText('0 Б')
    await clear(page, shot.id)
  })

  test('сводка медиатеки показывает, сколько сэкономило сжатие', async ({ page, isMobile }) => {
    const shot = await freshShot(page, '09.04')
    await clear(page, shot.id)
    const { file } = await uploadViaApi(page, compressibleImage(`library-${isMobile ? 'p' : 'd'}`), { entityType: 'shot', entityId: shot.id, purpose: 'reference' })
    expect((await compressed(page, file.id)).compression.state).toBe('done')
    await page.goto('/media')
    await expect(page.getByRole('status').filter({ hasText: /сжатие сэкономило/ })).toBeVisible()
    await clear(page, shot.id)
  })
})
