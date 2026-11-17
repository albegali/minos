import { defineConfig } from '@playwright/test'

const ci = Boolean(process.env.CI)

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: ci ? [['list'], ['html', { open: 'never' }]] : 'list',
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    // The specs look elements up by their Italian labels.
    locale: 'it-IT',
    viewport: { width: 1440, height: 900 },
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: './e2e/start-api.sh',
      url: 'http://127.0.0.1:8000/v1/ready',
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run build && npx vite preview --port 4173 --strictPort --host 127.0.0.1',
      url: 'http://127.0.0.1:4173',
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
