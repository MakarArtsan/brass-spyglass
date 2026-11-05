import { api, expect, test } from './fixtures'

interface ProjectInfo {
  title: string
  title_en: string
  slug: string
}

test.describe('переименование проекта', () => {
  test('владелец меняет название: оно видно в шапке и на дашборде, адрес не меняется', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/')
    const original = await api<ProjectInfo>(page, 'GET', '/project')
    try {
      await page.getByRole('button', { name: 'Переименовать проект' }).click()
      const dialog = page.getByRole('dialog', { name: 'Переименовать проект' })
      const save = dialog.getByRole('button', { name: 'Сохранить' })
      await expect(save).toBeDisabled() // пока ничего не изменено
      await dialog.getByLabel('Название', { exact: true }).fill('Кривое зеркало (тест)')
      await dialog.getByLabel('Название по-английски').fill('Crooked Mirror (test)')
      await expect(save).toBeEnabled()
      await save.click()
      await expect(dialog).toHaveCount(0)

      await expect(page.locator('header').getByText('Кривое зеркало (тест)')).toBeVisible()
      await expect(page.getByText('Crooked Mirror (test)')).toBeVisible()
      await expect(page).toHaveURL(/\/p\/brass-spyglass\/?$/) // адрес прежний

      await page.reload() // сохранилось на сервере
      await expect(page.locator('header').getByText('Кривое зеркало (тест)')).toBeVisible()
    } finally {
      await api(page, 'PATCH', '/project', { title: original.title, title_en: original.title_en })
    }
    expect((await api<ProjectInfo>(page, 'GET', '/project')).title).toBe(original.title)
  })

  test('пустое название не сохраняется', async ({ page, asRole }) => {
    await asRole('owner')
    await page.goto('/')
    await page.getByRole('button', { name: 'Переименовать проект' }).click()
    const dialog = page.getByRole('dialog', { name: 'Переименовать проект' })
    await dialog.getByLabel('Название', { exact: true }).fill('   ')
    await expect(dialog.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
  })

  for (const role of ['director', 'team', 'guest'] as const) {
    test(`роль «${role}» кнопки переименования не видит`, async ({ page, asRole }) => {
      await asRole(role)
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Переименовать проект' })).toHaveCount(0)
    })
  }
})
