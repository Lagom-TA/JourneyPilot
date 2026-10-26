import { test, expect } from '@playwright/test';

// Run against Vite dev: JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npm run test:e2e -- research-progress
// This fixture exercises real UI components, with synthetic events and no paid API calls.
test.skip(process.env.JP_COMPONENT_E2E !== '1', 'Requires Vite dev component fixture');
for (const width of [320, 390, 1440]) {
  test(`研究面板：并行归因、有效详情、停止状态 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/e2e/fixtures/research-progress.html');
    const panel = page.getByTestId('thinking-chain');
    await expect(panel).toContainText('3 个任务正在并行推进');
    await expect(panel).not.toContainText('contract_version');
    const destination = page.getByTestId('research-agent-destination');
    await destination.getByRole('button').click();
    const query = destination.getByTestId('research-query');
    await expect(query.locator('.research-source')).not.toBeVisible();
    await query.locator('summary').click();
    await expect(query).toContainText('长春市宽城区光复北路');
    await expect(query.getByRole('link', { name: '伪满皇宫博物院' })).toHaveAttribute('href', 'https://example.org/museum');
    const stay = page.getByTestId('research-agent-stay');
    await stay.getByRole('button').click();
    await expect(stay.getByTestId('research-query').first().locator('summary')).toHaveCount(0);
    await expect(stay).toContainText('能力边界');
    await page.getByRole('button', { name: '住宿直接返回', exact: true }).click();
    await expect(stay).toContainText('已整理 1 个住宿候选');
    await expect(stay.getByTestId('research-query')).toHaveCount(0);
    await page.getByRole('button', { name: '目的地完成', exact: true }).click();
    await expect(destination.locator('.research-agent-state')).toHaveText('已结束');
    await expect(page.getByTestId('research-agent-transport').locator('.research-agent-state')).toHaveText('进行中');
    await page.getByRole('button', { name: '停止', exact: true }).click();
    await expect(page.getByTestId('research-agent-transport').locator('.research-agent-state')).toHaveText('已停止');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  });
}
