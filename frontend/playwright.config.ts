import { defineConfig, devices } from '@playwright/test';

// 测试连接已启动的应用；服务由 run.sh 或 Compose 启动。
const baseURL = process.env.JOURNEYPILOT_APP_URL || 'http://127.0.0.1:8080';

export default defineConfig({
  testDir: './e2e',
  // 设置 CI 环境变量时：禁止遗留 .only（避免跳过其他用例）、失败重试一次、单 worker，并额外输出 JUnit 报告。
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
