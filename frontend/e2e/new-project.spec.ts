import type { Page } from '@playwright/test'
import { BASE_URL } from './session.mjs'
import { expect, test } from './fixtures'

// Настоящего Telegram в e2e нет: ответы сессии и /api/projects/* подменяются. Серверную часть (проверка чата,
// права, пределы, изоляция) покрывает pytest.

const USER = { id: 1, name: 'Артём', tg_username: 'artem', color: '#E8C979', role: 'owner', has_avatar: false, last_seen_at: null }
const FILM = { slug: 'brass-spyglass', title: 'Битва при кривом зеркале', title_en: 'The Brass Spyglass', role: 'owner', archived: false }
const CHATS = {
  ready: true,
  userbot: { username: 'brass_helper', name: 'Помощник' },
  chats: [
    { id: -1001110000001, title: 'Мой фильм' },
    { id: -1001110000002, title: 'Клип' },
  ],
  message: null,
}

async function mockSession(page: Page, extra: Record<string, unknown> = {}) {
  await page.route('**/api/session', (r) =>
    r.fulfill({ json: { user: USER, is_superadmin: false, projects: [], can_create_projects: true, ...extra } }),
  )
}

const mockChats = (page: Page, body: unknown) => page.route('**/api/projects/available-chats', (r) => r.fulfill({ json: body }))

test.describe('свой проект', () => {
  test('без проектов на экране есть кнопка «Создать проект»', async ({ page }) => {
    await mockSession(page)
    await page.goto(`${BASE_URL}/`)
    await expect(page.getByRole('heading', { name: 'У вас пока нет проектов' })).toBeVisible()
    await expect(page.getByText(/Создайте свой проект/)).toBeVisible()
    await page.getByRole('link', { name: 'Создать проект' }).click()
    await expect(page).toHaveURL(/\/new-project$/)
  })

  test('если создавать нельзя, кнопки нет, а экран создания объясняет почему', async ({ page }) => {
    await mockSession(page, { can_create_projects: false })
    await page.goto(`${BASE_URL}/`)
    await expect(page.getByRole('heading', { name: 'У вас пока нет проектов' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Создать проект' })).toHaveCount(0)
    await page.goto(`${BASE_URL}/new-project`)
    await expect(page.getByText('Новые проекты вам недоступны')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Создать проект' })).toHaveCount(0)
  })

  test('мастер: имя помощника, выбор чата, название, срок — и проект создаётся', async ({ page }) => {
    await mockSession(page)
    await mockChats(page, CHATS)
    let posted: Record<string, unknown> | null = null
    await page.route('**/api/projects', (r) => {
      if (r.request().method() !== 'POST') return r.fallback()
      posted = r.request().postDataJSON()
      return r.fulfill({
        status: 201,
        json: { slug: 'klip', title: 'Клип', title_en: 'Клип', role: 'owner', archived: false },
      })
    })
    await page.goto(`${BASE_URL}/new-project`)
    await expect(page.getByRole('heading', { name: 'Новый проект' })).toBeVisible()
    await expect(page.getByText('@brass_helper')).toBeVisible()
    const submit = page.getByRole('button', { name: 'Создать проект' })
    await expect(submit).toBeDisabled() // чат не выбран, названия нет

    await page.getByRole('radio', { name: 'Клип' }).click()
    await expect(page.getByLabel('Название', { exact: true })).toHaveValue('Клип') // подставилось из чата
    await page.getByLabel('Срок сдачи (необязательно)').fill('2099-01-31')
    await expect(submit).toBeEnabled()
    await submit.click()

    await expect(page).toHaveURL(/\/p\/klip\/$/)
    expect(posted).toEqual({ title: 'Клип', deadline: '2099-01-31', chat_id: -1001110000002 })
  })

  test('своё название не затирается выбором чата, английское уходит на сервер', async ({ page }) => {
    await mockSession(page)
    await mockChats(page, CHATS)
    let posted: Record<string, unknown> | null = null
    await page.route('**/api/projects', (r) => {
      if (r.request().method() !== 'POST') return r.fallback()
      posted = r.request().postDataJSON()
      return r.fulfill({ status: 201, json: { slug: 'crooked', title: 'Кривое', title_en: 'Crooked', role: 'owner', archived: false } })
    })
    await page.goto(`${BASE_URL}/new-project`)
    await page.getByLabel('Название', { exact: true }).fill('Кривое')
    await page.getByLabel('Название по-английски (необязательно)').fill('Crooked')
    await page.getByRole('radio', { name: 'Мой фильм' }).click()
    await expect(page.getByLabel('Название', { exact: true })).toHaveValue('Кривое')
    await page.getByRole('button', { name: 'Создать проект' }).click()
    await expect(page).toHaveURL(/\/p\/crooked\/$/)
    expect(posted).toEqual({ title: 'Кривое', title_en: 'Crooked', chat_id: -1001110000001 })
  })

  test.describe('бот-сборщик', () => {
    const BOT_CHATS = {
      ready: true,
      userbot: { username: 'brass_helper', name: 'Помощник' },
      bot: { username: 'brass_bot' },
      chats: [
        { id: -1001110000001, title: 'Мой фильм', via: 'bot', bot_admin: true },
        { id: -1001110000003, title: 'Без прав', via: 'bot', bot_admin: false },
        { id: -1001110000002, title: 'Клип', via: 'userbot', bot_admin: null },
      ],
      message: null,
    }
    const isQuick = (url: URL) => url.pathname === '/api/projects/available-chats' && url.searchParams.get('userbot') === 'false'
    const isFull = (url: URL) => url.pathname === '/api/projects/available-chats' && url.searchParams.get('userbot') === null

    test('инструкция про бота и /connect, метки «бот» и «помощник», предупреждение про права', async ({ page }) => {
      await mockSession(page)
      await page.route(isQuick, (r) => r.fulfill({ json: { ...BOT_CHATS, chats: BOT_CHATS.chats.slice(0, 2) } }))
      await page.route(isFull, (r) => r.fulfill({ json: BOT_CHATS }))
      await page.goto(`${BASE_URL}/new-project`)
      await expect(page.getByRole('heading', { name: '1. Подключите чат' })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Через бота сайта (рекомендуется)' })).toBeVisible()
      await expect(page.getByText('@brass_bot')).toBeVisible()
      await expect(page.getByText(/отправьте в чате команду \/connect/)).toBeVisible()
      await expect(page.getByText(/Историю чата он не видит/)).toBeVisible()
      await expect(page.getByText('@brass_helper')).toBeVisible() // прежний способ остаётся
      const hero = page.getByRole('radio', { name: /Мой фильм/ })
      await expect(hero).toContainText('бот')
      await expect(page.getByRole('radio', { name: /Клип/ })).toContainText('помощник')
      await expect(page.getByRole('radio', { name: /Без прав/ })).toContainText('Бот не администратор чата')
      await expect(hero).not.toContainText('Бот не администратор')
    })

    test('копируются имя бота и команда /connect', async ({ page, context }) => {
      await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE_URL }).catch(() => undefined)
      await mockSession(page)
      await page.route(isQuick, (r) => r.fulfill({ json: BOT_CHATS }))
      await page.route(isFull, (r) => r.fulfill({ json: BOT_CHATS }))
      await page.goto(`${BASE_URL}/new-project`)
      await page.getByRole('button', { name: 'Скопировать /connect' }).click()
      await expect(page.getByRole('button', { name: 'Скопировано' })).toBeVisible()
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('/connect')
    })

    test('чаты бота видны сразу, пока ищутся чаты помощника', async ({ page }) => {
      await mockSession(page)
      await page.route(isQuick, (r) => r.fulfill({ json: { ...BOT_CHATS, chats: [BOT_CHATS.chats[0]] } }))
      await page.route(isFull, async (r) => {
        await new Promise((resolve) => setTimeout(resolve, 1500))
        await r.fulfill({ json: BOT_CHATS })
      })
      await page.goto(`${BASE_URL}/new-project`)
      await expect(page.getByRole('radio', { name: /Мой фильм/ })).toBeVisible()
      await expect(page.getByRole('radio', { name: /Клип/ })).toHaveCount(0)
      await expect(page.getByText('Ищем и чаты помощника…')).toBeVisible()
      await expect(page.getByRole('radio', { name: /Клип/ })).toBeVisible()
      await expect(page.getByText('Ищем и чаты помощника…')).toHaveCount(0)
    })

    test('проект из чата бота создаётся с его chat_id', async ({ page }) => {
      await mockSession(page)
      await page.route(isQuick, (r) => r.fulfill({ json: BOT_CHATS }))
      await page.route(isFull, (r) => r.fulfill({ json: BOT_CHATS }))
      let posted: Record<string, unknown> | null = null
      await page.route('**/api/projects', (r) => {
        if (r.request().method() !== 'POST') return r.fallback()
        posted = r.request().postDataJSON()
        return r.fulfill({ status: 201, json: { slug: 'moy-film', title: 'Мой фильм', title_en: 'Мой фильм', role: 'owner', archived: false } })
      })
      await page.goto(`${BASE_URL}/new-project`)
      await page.getByRole('radio', { name: /Мой фильм/ }).click()
      await page.getByRole('button', { name: 'Создать проект' }).click()
      await expect(page).toHaveURL(/\/p\/moy-film\/$/)
      expect(posted).toEqual({ title: 'Мой фильм', chat_id: -1001110000001 })
    })

    test('чатов нет: подсказка говорит про /connect', async ({ page }) => {
      await mockSession(page)
      await page.route(isQuick, (r) => r.fulfill({ json: { ...BOT_CHATS, chats: [] } }))
      await page.route(isFull, (r) => r.fulfill({ json: { ...BOT_CHATS, chats: [] } }))
      await page.goto(`${BASE_URL}/new-project`)
      await expect(page.getByText(/Отправьте \/connect в чате, где бот уже администратор/)).toBeVisible()
    })

    test('на телефоне ничего не уезжает вбок, цели касания не меньше 44 px', async ({ page }) => {
      await mockSession(page)
      await page.route(isQuick, (r) => r.fulfill({ json: BOT_CHATS }))
      await page.route(isFull, (r) => r.fulfill({ json: BOT_CHATS }))
      await page.goto(`${BASE_URL}/new-project`)
      await expect(page.getByRole('radio', { name: /Без прав/ })).toBeVisible()
      for (const target of [
        page.getByRole('button', { name: 'Скопировать /connect' }),
        page.getByRole('button', { name: 'Найти мои чаты' }),
        page.getByRole('radio', { name: /Без прав/ }),
      ]) {
        expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(43.5)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
    })
  })

  test('нет подходящих чатов: подсказка, затем «Найти мои чаты» находит новый', async ({ page }) => {
    await mockSession(page)
    let calls = 0
    await page.route('**/api/projects/available-chats', (r) => {
      calls += 1
      return r.fulfill({ json: { ...CHATS, chats: calls === 1 ? [] : [CHATS.chats[1]] } })
    })
    await page.goto(`${BASE_URL}/new-project`)
    await expect(page.getByText(/Подходящих чатов пока нет/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Создать проект' })).toBeDisabled()
    await page.getByRole('button', { name: 'Найти мои чаты' }).click()
    await expect(page.getByRole('radio', { name: 'Клип' })).toBeVisible()
    await expect(page.getByText(/Подходящих чатов пока нет/)).toHaveCount(0)
  })

  test('Telegram недоступен: причина показана, создать нельзя', async ({ page }) => {
    await mockSession(page)
    await mockChats(page, { ready: false, userbot: null, chats: [], message: 'Подключение к Telegram сейчас недоступно. Попробуйте позже.' })
    await page.goto(`${BASE_URL}/new-project`)
    await expect(page.getByRole('alert')).toContainText('Подключение к Telegram сейчас недоступно')
    await expect(page.getByText(/имя пока недоступно/)).toBeVisible() // имени помощника нет
    await expect(page.getByRole('button', { name: 'Создать проект' })).toBeDisabled()
  })

  test('отказ сервера показан по-русски, человек остаётся на странице', async ({ page }) => {
    await mockSession(page)
    await mockChats(page, CHATS)
    await page.route('**/api/projects', (r) =>
      r.request().method() === 'POST'
        ? r.fulfill({ status: 403, json: { detail: 'Вы не администратор этого чата, или аккаунт юзербота не добавлен в него.' } })
        : r.fallback(),
    )
    await page.goto(`${BASE_URL}/new-project`)
    await page.getByRole('radio', { name: 'Мой фильм' }).click()
    await page.getByRole('button', { name: 'Создать проект' }).click()
    await expect(page.getByRole('alert')).toContainText('Вы не администратор этого чата')
    await expect(page).toHaveURL(/\/new-project$/)
  })

  test('администратор сайта может создать проект без чата', async ({ page }) => {
    await mockSession(page, { is_superadmin: true })
    await mockChats(page, { ...CHATS, chats: [] })
    await page.goto(`${BASE_URL}/new-project`)
    const noChat = page.getByRole('radio', { name: /Без чата/ })
    await expect(noChat).toBeVisible()
    await noChat.click()
    await page.getByLabel('Название', { exact: true }).fill('Черновик')
    await expect(page.getByRole('button', { name: 'Создать проект' })).toBeEnabled()
  })

  test('выбор чата — крупная цель касания', async ({ page }) => {
    await mockSession(page)
    await mockChats(page, CHATS)
    await page.goto(`${BASE_URL}/new-project`)
    for (const name of ['Мой фильм', 'Клип']) {
      const box = await page.getByRole('radio', { name }).boundingBox()
      expect(box!.height).toBeGreaterThanOrEqual(44)
    }
  })

  test('в проекте есть ссылка «Новый проект», если создавать можно', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await mockSession(page, { projects: [FILM] })
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    const link = page.getByRole('link', { name: 'Новый проект' }).filter({ visible: true })
    await expect(link).toBeVisible()
    const box = await link.boundingBox()
    expect(box!.height).toBeGreaterThanOrEqual(44)
    await link.click()
    await expect(page).toHaveURL(/\/new-project$/)
  })

  test('без права создавать ссылки в проекте нет', async ({ page, asRole, isMobile }) => {
    await asRole('owner')
    await mockSession(page, { projects: [FILM], can_create_projects: false })
    await page.goto('/')
    if (isMobile) await page.getByRole('button', { name: 'Ещё' }).click()
    await expect(page.getByRole('link', { name: 'Новый проект' })).toHaveCount(0)
  })

  test('без входа экран создания ведёт на вход', async ({ page }) => {
    await page.goto(`${BASE_URL}/new-project`)
    await expect(page).toHaveURL(/\/login$/)
  })
})
