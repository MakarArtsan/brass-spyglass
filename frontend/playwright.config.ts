import { defineConfig } from '@playwright/test'
import { BASE_URL } from './e2e/session.mjs'

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts/,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: BASE_URL },
  // Поднимает приложение целиком (API + собранный фронтенд) на чистой БД.
  webServer: {
    command: 'bash e2e/serve.sh',
    url: `${BASE_URL}/api/health`,
    timeout: 60_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    {
      name: 'phone',
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
    },
  ],
})
