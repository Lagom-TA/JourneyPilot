import { defineConfig, devices } from '@playwright/test';

// 测试连接已启动的应用；服务由 run.sh 或 Compose 启动。
const baseURL = process.env.JOURNEYPILOT_APP_URL || 'http://127.0.0.1:8080';

export default defineConfig({
  testDir: './e2e',
  // 防止 CI 因 .only 而跳过其他测试。
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['list'], ['junit', { outputFile: 'test-results/playwright-junit.xml' }]]
    : 'list',
  use: {
    baseURL,
    // 为失败用例保留诊断信息。
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
