import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

// 只使用 live 套件创建的一次性行程，不要指向用户的行程。
test('真实交付修改：添加安排 → 报告同步 → 刷新 → 撤销', async ({ page, request }, testInfo) => {
  const runId = process.env.JP_EDIT_RUN_ID;
  test.skip(!runId, 'Set JP_EDIT_RUN_ID to a disposable completed test trip');
  test.setTimeout(120_000);
  page.setDefaultTimeout(15_000);
  const detail = await (await request.get(`/api/trip-runs/${runId}`)).json();
  expect(detail.run.status).toBe('completed');
  const url = `/api/trip-runs/${runId}/bundle/current`;
  const original = await (await request.get(url)).json();
  const name = `E2E临时休息安排-${Date.now()}`;
  await page.addInitScript(sessionId => localStorage.setItem('sta_last_session_id', sessionId), detail.run.session_id);
  await page.goto('/');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('itinerary-day-nav').getByRole('button', { name: '第 1 天', exact: true }).click();
  await page.getByTestId('add-custom-day_1').click();
  const form = page.getByRole('region', { name: '第 1 天添加自定义安排' });
  await form.getByLabel('标题', { exact: true }).fill(name);
  await form.getByLabel('备注', { exact: true }).fill('临时端到端测试，验证后撤销。');
  const previewPromise = page.waitForResponse(response => response.url().endsWith('/workspace/mutations/preview'));
  await form.getByRole('button', { name: '保存到第 1 天' }).click();
  const previewResponse = await previewPromise;
  expect(previewResponse.ok()).toBeTruthy();
  if ((await previewResponse.json()).requires_confirmation) {
    await page.getByRole('button', { name: '确认调整', exact: true }).click();
  }
  await expect.poll(async () => {
    const bundle = await (await request.get(url)).json();
    return bundle.workspace.itinerary.custom_blocks.some((item: { title: string }) => item.title === name);
  }, { timeout: 30_000 }).toBe(true);
  await page.getByRole('tab', { name: '完整报告' }).click();
  await expect(page.getByTestId('full-report')).toContainText(name, { timeout: 30_000 });
  const edited = await (await request.get(url)).json();
  expect(edited.manifest.workspace_revision).toBeGreaterThan(original.manifest.workspace_revision);
  expect(edited.report_projection.source_workspace_revision).toBe(edited.manifest.workspace_revision);
  await page.reload();
  await expect(page.getByTestId('delivery-undo')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('delivery-undo').click();
  await expect.poll(async () => {
    const bundle = await (await request.get(url)).json();
    return bundle.workspace.itinerary.custom_blocks.some((item: { title: string }) => item.title === name);
  }, { timeout: 30_000 }).toBe(false);
  const restored = await (await request.get(url)).json();
  expect(restored.workspace.itinerary).toEqual(original.workspace.itinerary);
  expect(restored.manifest.workspace_revision).toBeGreaterThan(edited.manifest.workspace_revision);
  await page.getByRole('tab', { name: '完整报告' }).click();
  await expect(page.getByTestId('report-cover')).toBeVisible();
  await expect(page.getByTestId('full-report')).not.toContainText(name);
  await writeFile(testInfo.outputPath('revisions.json'), JSON.stringify({
    runId, original: original.manifest, edited: edited.manifest, restored: restored.manifest,
  }, null, 2));
});
