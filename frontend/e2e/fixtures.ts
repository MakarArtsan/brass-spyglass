import { test as base, expect, type BrowserContext } from '@playwright/test'
import { BASE_URL, sessionCookie } from './session.mjs'

type Role = 'owner' | 'director' | 'team' | 'guest'

const PEOPLE: Record<Role, { name: string; tgId: number; username: string }> = {
  owner: { name: 'Артём', tgId: 900001, username: 'artem' },
  director: { name: 'Дина', tgId: 900002, username: 'dina' },
  team: { name: 'Петя', tgId: 900003, username: 'petya' },
  guest: { name: 'Гость', tgId: 900004, username: 'guest' },
}

export async function signIn(context: BrowserContext, role: Role = 'owner') {
  const value = sessionCookie({ ...PEOPLE[role], role })
  await context.addCookies([{ name: 'bs_session', value, url: BASE_URL, httpOnly: true }])
}

export const test = base.extend<{ asRole: (role: Role) => Promise<void> }>({
  asRole: async ({ context }, use) => {
    await use((role) => signIn(context, role))
  },
})

export { expect }
