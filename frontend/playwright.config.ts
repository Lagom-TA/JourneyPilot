import { defineConfig, devices } from '@playwright/test';

// 测试连接已启动的应用；服务由 run.sh 或 Compose 启动。
const baseURL = process.env.JOURNEYPILOT_APP_URL || 'http://127.0.0.1:8080';
// 这些用例依赖真实 API、已有行程或定制部署；其余用例只使用合成数据与本地前端。
const integrationSpecs = /(?:^|[/\\])(?:smoke|workspace|mobile-navigation|live-planning|delivery-readonly|deployment-settings)\.spec\.ts$/;

export default defineConfig({
  testDir: './e2e',
  // CI 保留一次重试帮助诊断；首次失败仍使门禁失败，避免重试成功掩盖不稳定行为。
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  failOnFlakyTests: !!process.env.CI,
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
  projects: [
    { name: 'offline', testIgnore: integrationSpecs, use: { ...devices['Desktop Chrome'] } },
    { name: 'integration', testMatch: integrationSpecs, use: { ...devices['Desktop Chrome'] } },
  ],
});
