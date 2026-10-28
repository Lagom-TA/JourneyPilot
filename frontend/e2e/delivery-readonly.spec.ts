import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

// 只读取已完成的测试行程，不向用户的旅行写入任何直接编辑。
test('真实交付只读：地图、会话、阅读版、PDF 与旅中视图', async ({ page, request }, testInfo) => {
  const runId = process.env.JP_READ_RUN_ID || process.env.JP_EDIT_RUN_ID;
  test.skip(!runId, 'Set JP_READ_RUN_ID to a completed test trip');
  test.setTimeout(120_000);
  page.setDefaultTimeout(15_000);
  const detail = await (await request.get(`/api/trip-runs/${runId}`)).json();
  expect(detail.run.status).toBe('completed');
  await page.addInitScript(sessionId => localStorage.setItem('sta_last_session_id', sessionId), detail.run.session_id);
  await page.goto('/');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible({ timeout: 30_000 });
  // 只读交付的边界：不出现编辑入口，也不出现会话页的引导标题。
  await expect(page.getByRole('heading', { name: '想去哪里，告诉我。' })).toHaveCount(0);
  await expect(page.locator('[data-testid^="add-custom-"]')).toHaveCount(0);
  await expect(page.getByTestId('delivery-undo')).toHaveCount(0);
  // 只读 Run 不渲染「告诉我想怎么改……」入口；footer 提示只读状态。
  await expect(page.getByRole('button', { name: '告诉我想怎么改……' })).toHaveCount(0);
  await expect(page.getByText('这份生成记录仅供查看')).toBeVisible();

  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  await expect(page.getByTestId('report-cover')).toBeVisible();
  await expect(page.getByTestId('full-report')).not.toContainText('其它合格选择');
  await expect(page.getByTestId('full-report')).not.toContainText('出发前事项');
  await expect(page.getByTestId('full-report')).not.toContainText('数据说明');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('region', { name: '旅行阅读版' }).getByTestId('download-current-pdf').click();
  const download = await downloadPromise;
  const pdfPath = testInfo.outputPath('trip.pdf');
  await download.saveAs(pdfPath);
  const pdf = await readFile(pdfPath);
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.length).toBeGreaterThan(10_000);

  await page.getByRole('button', { name: '返回地图' }).click();
  await page.getByRole('button', { name: '旅中查看' }).click();
  await expect(page.getByRole('region', { name: '接下来的安排' })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId('sidebar-open').click();
  const mobileNavigation = page.getByRole('dialog', { name: '主导航' });
  await expect(mobileNavigation).toBeVisible();
  await expect.poll(() => mobileNavigation.evaluate((node) => node.getBoundingClientRect().left)).toBe(0);
  await page.screenshot({ path: testInfo.outputPath('phone-navigation-open.png'), fullPage: true });
  await page.getByRole('button', { name: '收起侧栏', exact: true }).click();
  await expect(mobileNavigation).toHaveCount(0);
  await expect(page.getByTestId('sidebar-scrim')).toHaveCount(0);
  await page.getByTestId('canvas-pill').click();
  const canvasSheet = page.getByTestId('canvas-sheet');
  await expect(canvasSheet.getByTestId('interactive-itinerary')).toBeVisible();
  await expect.poll(() => canvasSheet.evaluate((node) => node.getBoundingClientRect().top)).toBeLessThan(500);
  await page.screenshot({ path: testInfo.outputPath('phone-sheet-open.png'), fullPage: true });
  await canvasSheet.screenshot({ path: testInfo.outputPath('phone-sheet-panel.png') });
  await page.getByTestId('canvas-sheet').getByRole('button', { name: '阅读版', exact: true }).click();
  await expect(page.getByTestId('report-cover')).toBeVisible();
});