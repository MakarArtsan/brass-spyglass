import { BASE_URL } from './session.mjs'
import { expect, test } from './fixtures'

// Адрес проекта — `/p/<slug>/…`. Все остальные тесты открывают страницы уже внутри проекта (fixtures.ts),
// поэтому переход со старых ссылок и пограничные случаи проверяются здесь, на полных адресах.

test.describe('проекты', () => {
  test('старая ссылка без проекта переносится в проект целиком, с параметрами', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto(`${BASE_URL}/shots?shot=1#row`)
    await expect(page).toHaveURL(/\/p\/brass-spyglass\/shots\?shot=1#row$/)
    await expect(page.locator('[data-shot]').first()).toBeVisible()
  })

  test('корень ведёт в последний открытый проект', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto(`${BASE_URL}/`)
    await expect(page).toHaveURL(/\/p\/brass-spyglass\/?$/)
  })

  test('без сессии адрес проекта ведёт на экран входа', async ({ page }) => {
    await page.goto(`${BASE_URL}/p/brass-spyglass/shots`)
    await expect(page).toHaveURL(/\/login$/)
  })

  test('несуществующий проект выглядит как чужой: «не найден» и путь к своим', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/p/no-such-film/')
    await expect(page.getByRole('heading', { name: 'Проект не найден' })).toBeVisible()
    await expect(page.getByText('Такого проекта нет или у вас нет к нему доступа.')).toBeVisible()
    await page.getByRole('link', { name: 'К моим проектам' }).click()
    await expect(page).toHaveURL(/\/p\/brass-spyglass\/?$/)
  })

  test('с одним проектом переключателя нет', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    await expect(page.getByLabel(/^Проект/)).toHaveCount(0)
  })

  test('с двумя проектами переключатель открывает другой проект новой загрузкой страницы', async ({
    page,
    asRole,
    isMobile,
  }) => {
    await asRole('owner')
    await page.route('**/api/session', (r) =>
      r.fulfill({
        json: {
          user: { id: 1, name: 'Артём', tg_username: 'artem', color: '#E8C979', role: 'owner', has_avatar: false, last_seen_at: null },
          is_superadmin: true,
          projects: [
            { slug: 'brass-spyglass', title: 'Битва при кривом зеркале', title_en: 'The Brass Spyglass', role: 'owner', archived: false },
            { slug: 'second-film', title: 'Второй фильм', title_en: 'Second', role: 'owner', archived: false },
          ],
        },
      }),
    )
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    // на телефоне боковая панель (с таким же переключателем) скрыта, поэтому берём только видимый
    const switcher = page.getByLabel(/^Проект/).filter({ visible: true })
    await expect(switcher).toBeVisible()
    await switcher.selectOption('second-film')
    await expect(page).toHaveURL(/\/p\/second-film\/?$/)
    // настоящего второго проекта в базе e2e нет: сервер отвечает 404, сайт показывает «не найден»
    await expect(page.getByRole('heading', { name: 'Проект не найден' })).toBeVisible()
  })
})
