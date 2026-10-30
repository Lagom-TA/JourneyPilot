import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

test('逐项核对无默认选择，未确认的要求不能变成计划授权', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const escaped: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) { escaped.push(url.href); return route.abort(); }
    return route.continue();
  });
  await page.goto('/e2e/fixtures/semantic-gate.html');
  const coffee = page.getByRole('group', { name: '对“咖啡”这条完整理解的处理' });
  const tokyo = page.getByRole('group', { name: '对“东京”这条完整理解的处理' });
  const coffeeCard = page.locator('.semantic-gate-card').filter({ has: coffee });
  const confirm = page.getByRole('button', { name: '提交需求确认' });
  await expect(confirm).toBeDisabled();
  await expect(page.getByRole('radio', { checked: true })).toHaveCount(0);
  await expect(coffeeCard.getByText('预算口径', { exact: true })).toBeVisible();
  await expect(coffeeCard.getByText('total', { exact: true })).toBeVisible();
  await expect(coffeeCard.getByText('全体同行：2 位成人、0 位儿童', { exact: true })).toBeVisible();
  await coffee.getByLabel('不采用此理解').check();
  await tokyo.getByLabel('暂不确定').check();
  await expect(confirm).toBeDisabled();
  await tokyo.getByLabel('仅历史背景').check();
  await expect(confirm).toBeEnabled();
  await page.getByLabel('更正说明').fill('不喝咖啡，请保留饮食限制');
  await page.reload();
  await expect(coffee.getByLabel('不采用此理解')).toBeChecked();
  await expect(tokyo.getByLabel('仅历史背景')).toBeChecked();
  await expect(page.getByLabel('更正说明')).toHaveValue('不喝咖啡，请保留饮食限制');
  mkdirSync('../output/polish/20261030-1012-model-research-plan', { recursive: true });
  await page.screenshot({ path: '../output/polish/20261030-1012-model-research-plan/semantic-gate-390.png', fullPage: true });
  await confirm.click();
  await expect(page.getByRole('alert')).toContainText('服务端没有接受');
  await page.reload();
  await expect(coffee.getByLabel('不采用此理解')).toBeChecked();
  await page.evaluate(() => { (window as unknown as { __semanticProbe: { accept: boolean } }).__semanticProbe.accept = true; });
  await confirm.click();
  await expect(page.getByText('这次需求确认已提交。')).toBeVisible();
  const sent = await page.evaluate(() => (window as unknown as { __semanticProbe: { confirmations: unknown[] } }).__semanticProbe.confirmations);
  expect(sent).toEqual([{ challenge_id: 'offline-challenge', approval_token: 'offline-token', revision: 1, decisions: [
    { assertion_id: 'coffee', decision: 'avoid' }, { assertion_id: 'tokyo', decision: 'historical' },
  ] }]);
  expect(JSON.stringify(sent)).not.toContain('不喝咖啡');
  expect(errors).toEqual([]);
  expect(escaped).toEqual([]);
});
