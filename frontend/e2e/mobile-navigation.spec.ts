import { expect, test } from '@playwright/test';

for (const width of [320, 390, 768]) {
  test(`移动导航与规划表在 ${width}px 下可用`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await expect(page.getByRole('heading', { name: '想去哪里，告诉我。' })).toBeVisible();
    await page.getByRole('tab', { name: '按条件规划' }).click();
    const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
    const originInput = page.getByRole('textbox', { name: '从哪里出发' });
    await expect(skip.or(originInput)).toBeVisible();
    if (await skip.count()) await skip.click();
    await expect(page.getByRole('textbox', { name: '从哪里出发' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: '去哪里', exact: true })).toBeVisible();
    const scroll = page.locator('.new-trip-hero');
    expect(await scroll.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);

    const opener = page.getByRole('button', { name: '打开导航', exact: true });
    const sidebar = page.getByTestId('app-sidebar');
    await expect(sidebar).toHaveAttribute('inert', '');
    await opener.click();
    await expect(page.getByRole('dialog', { name: '主导航' })).toBeVisible();
    await expect(page.locator('main')).toHaveAttribute('inert', '');
    await page.getByRole('button', { name: '收起侧栏', exact: true }).focus();
    await page.keyboard.press('Shift+Tab');
    await expect(page.getByRole('link', { name: '我的偏好', exact: true })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: '收起侧栏', exact: true })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
    await expect(sidebar).toHaveAttribute('inert', '');

    await opener.click();
    await page.getByRole('link', { name: '旅行风格', exact: true }).click();
    await expect(page.getByRole('dialog', { name: '主导航' })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '旅行风格', exact: true })).toBeVisible();
    await expect(page.locator('main')).not.toHaveAttribute('inert');
  });
}
