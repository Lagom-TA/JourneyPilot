import { defineConfig, devices } from '@playwright/test';

// Connect to an already running app; run.sh and Compose own service startup.
const baseURL = process.env.JOURNEYPILOT_APP_URL || 'http://127.0.0.1:8080';

export default defineConfig({
  testDir: './e2e',
  // CI 上禁止 .only：一个漏掉的 .only 会让整套门禁静默只跑一个用例。
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['list'], ['junit', { outputFile: 'test-results/playwright-junit.xml' }]]
    : 'list',
  use: {
    baseURL,
    // 失败时留下能看的东西：一次 CI 上的 e2e 失败如果只有一行报错，等于没有诊断。
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
