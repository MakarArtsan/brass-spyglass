import { api, expect, sampleMedia, test, uploadViaApi } from './fixtures'

interface SceneRef {
  id: number
  order: number
  status: string
}

/** Первая по порядку сцена с готовым видео; после теста всё возвращается как было. */
async function withReadyScene(page: import('@playwright/test').Page, run: (scene: SceneRef) => Promise<void>) {
  const scenes = (await api<SceneRef[]>(page, 'GET', '/scenes')).sort((a, b) => a.order - b.order)
  const scene = scenes[0]
  const { file } = await uploadViaApi(page, sampleMedia().video, { entityType: 'scene', entityId: scene.id, purpose: 'final' })
  await expect
    .poll(async () => (await api<{ processing: boolean; duration_sec: number | null }>(page, 'GET', `/files/${file.id}`)).duration_sec, { timeout: 30_000 })
    .not.toBeNull()
  await api(page, 'PUT', `/scenes/${scene.id}/final`, { file_id: file.id })
  await api(page, 'PATCH', `/scenes/${scene.id}`, { status: 'done' })
  try {
    await run(scene)
  } finally {
    await api(page, 'PATCH', `/scenes/${scene.id}`, { status: scene.status })
    await api(page, 'PUT', `/scenes/${scene.id}/final`, { file_id: null })
    await api(page, 'DELETE', `/files/${file.id}`)
  }
}

test.describe('экспорт в Resolve и Premiere', () => {
  test.setTimeout(120_000)
  test.beforeEach(async ({ asRole }) => asRole('owner'))

  test('экран: параметры, предпросмотр таймлайна, плейсхолдеры закрывают дыры', async ({ page }) => {
    await page.goto('/export')
    await expect(page.getByRole('heading', { name: 'Экспорт', level: 1 })).toBeVisible()
    await expect(page.getByRole('radio', { name: 'DaVinci Resolve' })).toBeChecked()
    await expect(page.getByText(/На таймлайне пока ничего/)).toBeVisible()
    await page.getByRole('checkbox', { name: /Плейсхолдеры/ }).check()
    const preview = page.getByRole('list', { name: 'Что попадёт на таймлайн' })
    await expect(preview.getByRole('listitem')).toHaveCount(12)
    await expect(preview.getByRole('listitem').first()).toContainText('01:00:00:00')
    await expect(page.getByText(/Клипов: 0 \+ заглушек: 12/)).toBeVisible()
    await page.getByRole('radio', { name: 'Шоты' }).click()
    await expect(preview.getByRole('listitem')).toHaveCount(69)
  })

  test('пакет собирается в фоне, появляется в истории и скачивается zip-архивом', async ({ page }) => {
    await withReadyScene(page, async () => {
      await page.goto('/export')
      await page.getByRole('textbox', { name: /Папка у вас на диске/ }).fill('D:/BrassSpyglass/')
      await expect(page.getByText(/^Клипов: 1 · \d+:\d{2}$/)).toBeVisible()
      await page.getByRole('button', { name: 'Собрать пакет' }).click()
      const row = page.getByRole('listitem').filter({ hasText: 'собрал Артём' }).first()
      await expect(row.getByText('Готов')).toBeVisible({ timeout: 60_000 })
      const link = row.getByRole('link', { name: 'Скачать zip' })
      await expect(link).toBeVisible()
      const href = await link.getAttribute('href')
      const response = await page.request.get(href!)
      expect(response.status()).toBe(200)
      expect(response.headers()['content-type']).toBe('application/zip')
      expect((await response.body()).subarray(0, 2).toString()).toBe('PK')
    })
  })

  test('без готовых сцен сборка сообщает причину, а не молчит', async ({ page }) => {
    await page.goto('/export')
    await page.getByRole('button', { name: 'Собрать пакет' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'нечего собирать' }).first()).toBeVisible({ timeout: 30_000 })
  })

  test('на экране «Звук» есть выгрузка субтитров', async ({ page }) => {
    await page.goto('/sound')
    const link = page.getByRole('link', { name: 'Экспорт субтитров (.srt)' })
    await expect(link).toHaveAttribute('href', '/api/subtitles.srt')
    const response = await page.request.get('/api/subtitles.srt')
    expect(response.status()).toBe(200)
    expect(await response.text()).toContain('We are poor. But they? Look how they shine!')
  })

  test('гость не видит экспорт: пункта нет, прямая ссылка уводит на дашборд', async ({ page, asRole, isMobile }) => {
    await asRole('guest')
    await page.goto('/export')
    await expect(page).toHaveURL(/\/$/)
    if (!isMobile) await expect(page.getByRole('link', { name: 'Экспорт', exact: true })).toHaveCount(0)
    await page.goto('/sound')
    await expect(page.getByRole('link', { name: 'Экспорт субтитров (.srt)' })).toHaveCount(0)
  })
})
