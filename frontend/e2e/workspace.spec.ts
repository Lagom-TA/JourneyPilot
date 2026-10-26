import { expect, test } from '@playwright/test';

test('侧栏导航、浏览器后退与刷新恢复', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  for (const name of ['资料来源', '旅行风格', '我的偏好']) {
    await page.getByRole('link', { name, exact: true }).click();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  }
  await page.goBack();
  await expect(page.getByRole('heading', { name: '旅行风格', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '旅行风格', exact: true })).toBeVisible();
  await page.getByPlaceholder('搜索旅行风格...').fill('no-such-preset-e2e');
  await expect(page.getByText('没有找到匹配的旅行风格', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('真实资料库：上传、读取、修改、刷新、删除自己的测试文件', async ({ page, request }) => {
  test.skip(process.env.JP_WRITE_E2E !== '1', 'Set JP_WRITE_E2E=1 to exercise persistent writes');
  test.setTimeout(180_000);
  const name = `e2e-${Date.now()}-travel-notes.txt`;
  const content = '端到端测试资料：这是一份用于验证资料上传和读取的临时旅行备忘录，不作为真实旅行建议。';
  const revised = `${content}\n更新内容：出门前检查证件，携带饮用水。`;
  const sourceURL = `/api/knowledge/collections/travel_knowledge/source?source=${encodeURIComponent(name)}`;
  try {
    await page.goto('/?view=knowledge-base');
    await expect(page.getByRole('heading', { name: '资料来源', exact: true })).toBeVisible();
    const uploaded = page.waitForResponse(response => response.url().endsWith('/api/knowledge/upload-file'));
    await page.locator('input[type=file]').setInputFiles({ name, mimeType: 'text/plain', buffer: Buffer.from(content) });
    expect((await uploaded).ok()).toBeTruthy();
    const row = page.getByTestId(`knowledge-source-row-${name}`);
    await row.click({ timeout: 90_000 });
    const body = page.getByRole('textbox', { name: '资料正文' });
    await expect(body).toHaveValue(content);
    await body.fill(revised);
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 60_000 });
    await page.reload();
    await row.click();
    await expect(body).toHaveValue(revised);
    await page.getByRole('button', { name: '删除这篇', exact: true }).click();
    await page.getByRole('button', { name: '删除', exact: true }).click();
    await expect(page.getByRole('dialog')).not.toBeVisible();
    await expect(row).toHaveCount(0);
    expect((await request.get(sourceURL)).status()).toBe(404);
  } finally {
    // 只删除本次唯一命名的测试文档，不清空用户的资料库。
    const response = await request.delete(sourceURL);
    expect([200, 404]).toContain(response.status());
  }
});

test('真实旅行风格：创建、刷新、编辑、删除自己的测试风格', async ({ page, request }) => {
  test.skip(process.env.JP_WRITE_E2E !== '1', 'Set JP_WRITE_E2E=1 to exercise persistent writes');
  test.setTimeout(90_000);
  page.setDefaultTimeout(15_000);
  const name = `E2E-${Date.now()}`;
  let presetId = '';
  try {
    await page.goto('/?view=presets');
    await page.getByRole('button', { name: '创建风格', exact: true }).click();
    await page.getByPlaceholder('如：日本温泉之旅').fill(name);
    await page.getByPlaceholder('如：带孩子的慢节奏文化游').fill('端到端测试临时风格');
    await page.getByRole('button', { name: '下一步', exact: true }).click();
    await page.getByRole('dialog').locator('textarea').fill('每天保留休息时间，优先推荐步行可达的活动。');
    await page.getByRole('button', { name: '下一步', exact: true }).click();
    await page.getByRole('button', { name: '下一步', exact: true }).click();
    const created = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/presets'));
    await page.getByRole('button', { name: '创建旅行风格', exact: true }).click();
    const response = await created;
    expect(response.ok()).toBeTruthy();
    presetId = (await response.json()).id;
    expect(presetId).toBeTruthy();
    await page.reload();
    const card = page.getByTestId(`preset-card-${presetId}`);
    await expect(card).toContainText(name);
    await card.getByRole('button', { name: '编辑这个风格' }).click();
    await page.getByPlaceholder('如：日本温泉之旅').fill(`${name}-edited`);
    for (let step = 0; step < 3; step++) await page.getByRole('button', { name: '下一步', exact: true }).click();
    await page.getByRole('button', { name: '保存修改', exact: true }).click();
    await expect(card).toContainText(`${name}-edited`);
    await card.getByRole('button', { name: '删除这个风格' }).click();
    await card.getByRole('button', { name: '删除', exact: true }).click();
    await expect(card).toHaveCount(0);
  } finally {
    if (presetId) {
      const response = await request.delete(`/api/presets/${encodeURIComponent(presetId)}`);
      expect([200, 204, 404]).toContain(response.status());
    }
  }
});
