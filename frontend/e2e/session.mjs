import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../backend')

/** Значение cookie сессии для тестового участника (см. backend/scripts/dev_session.py). */
export function sessionCookie({ name = 'Артём', tgId = 900001, username = 'artem', role = 'owner' } = {}) {
  const dataDir = process.env.E2E_DATA_DIR ?? path.join(backend, '.e2e-data')
  return execFileSync(
    path.join(backend, '.venv/bin/python'),
    [
      'scripts/dev_session.py',
      '--name', name,
      '--tg-id', String(tgId),
      '--username', username,
      '--role', role,
    ],
    {
      cwd: backend,
      encoding: 'utf8',
      env: { ...process.env, DATA_DIR: dataDir, SESSION_SECRET: 'e2e-secret', OWNER_TG_ID: '900001' },
    },
  ).trim()
}

export const BASE_URL = process.env.E2E_URL ?? 'http://127.0.0.1:8765'
