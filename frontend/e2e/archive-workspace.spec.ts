import { test, expect, type Page } from '@playwright/test';
import { sessionDetail, sessionSummary } from './fixtures/sessionData';
import { xianLayoutBundle } from './fixtures/xianBundle';

async function fixture(page: Page) {
  const errors: string[] = [], unexpectedWrites: string[] = [], writes: Array<{ path: string; method: string; body: unknown }> = [];
  const controls = { memoryFailure: false, profileFailure: false, presetDeleteFailure: false, presetSaveFailure: false, sourceSaveFailure: false, sourceReadFailure: false, sourceDeleteFailure: false, textFailure: false };
  const origin = { place_id: 'city-shanghai', provider: 'amap', kind: 'city', name: '上海', display_name: '上海市，中国', country_code: 'CN', latitude: 31.23, longitude: 121.47, admin_path: ['中国', '上海市'] };
  const presets = Array.from({ length: 6 }, (_, i) => ({ id: `style-${i}`, name: ['深度文化游', '美食探店', '亲子度假', '户外探险', '摄影旅拍', '慢走城市'][i], description: ['博物馆、街区与当地文化。', '以特色餐厅与本地市场组织旅行。', '短距离移动，每天保留休息。', '徒步、自然与户外体验。', '为光线与取景留出时间。', '在街巷、建筑与步行之间探索。'][i], icon: 'compass', category: 'culture', instructions: '每天集中探索一个区域，减少往返；重要地点留出充分时间。', constraints: { pace: '悠闲', focus_areas: ['文化', '建筑'] }, is_preset: i < 5, usage_count: 0, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z' }));
  let facts = [{ fact_id: 'manual', content: '不安排清晨出发的航班', source: 'manual', category: 'preference', created_at: '2026-11-05T00:00:00Z' }, { fact_id: 'auto', content: '喜欢在老街区散步', source: 'auto', category: 'preference', created_at: '2026-11-04T00:00:00Z' }];
  let documents = [{ source: '京都步行笔记.md', content: '东山一带适合步行串联。\n清水寺与二年坂安排在同一天，午后留出休息时间。', chunk_count: 2 }, { source: '住宿备选.pdf', content: '优先考虑公共交通方便、可步行到车站的住宿。', chunk_count: 1 }];
  const runs = [
    { run_id: 'run-A', session_id: 'A', status: 'completed', title: '深圳 → 西安 · 11/1–11/3', created_at: '2026-11-05T00:00:00Z', updated_at: '2026-11-05T00:00:00Z', mode: 'deep' },
    { run_id: 'run-old', session_id: 'A', status: 'completed', title: '深圳 → 西安 · 11/1–11/3', created_at: '2026-11-04T00:00:00Z', updated_at: '2026-11-04T00:00:00Z', mode: 'deep' },
    { run_id: 'run-B', session_id: 'B', status: 'awaiting_input', title: '京都五日', created_at: '2026-11-03T00:00:00Z', updated_at: '2026-11-03T00:00:00Z', mode: 'deep' },
    { run_id: 'run-C', session_id: 'C', status: 'cancelled', title: '大理周末', created_at: '2026-11-02T00:00:00Z', updated_at: '2026-11-02T00:00:00Z', mode: 'deep' },
  ];
  await page.addInitScript(() => localStorage.removeItem('journeypilot.last-session-id'));
  page.on('pageerror', err => errors.push(err.message));
  await page.route('**/appmaptile?**', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e9e8df"/></svg>' }));
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4), method = request.method();
    let body: unknown = [], status = 200;
    if (method !== 'GET') writes.push({ path, method, body: request.postData()?.startsWith('{') ? request.postDataJSON() : null });
    if (path === '/user/sessions') body = ['A', 'B', 'C', 'D'].map(id => ({ ...sessionSummary(id), title: id === 'D' ? '苏州园林怎么选' : runs.find(run => run.session_id === id)?.title, last_message_preview: '## 不应重复展示的 Markdown 回答' }));
    else if (/^\/user\/sessions\/[A-D]$/.test(path)) body = sessionDetail(path.at(-1)!);
    else if (path === '/trip-runs') body = { runs: runs.filter(run => !url.searchParams.get('session_id') || run.session_id === url.searchParams.get('session_id')), total: 4 };
    else if (/^\/trip-runs\/[^/]+$/.test(path)) body = { run: runs.find(run => run.run_id === path.split('/').at(-1)), state: { pending_user_choice: null, latest_state_summary: {} }, execution: null, available_actions: [], events: [] };
    else if (path.endsWith('/bundle/current')) body = JSON.parse(JSON.stringify(xianLayoutBundle({ dayCount: 3 }), (_key, value) => value === 'run-A' ? path.split('/')[2] : value));
    else if (path.endsWith('/events')) body = { events: [], run_status: 'completed', latest_sequence: 0, replay_floor_sequence: 1, window_expired: false };
    else if (path === '/config') body = { ingest: { max_upload_bytes: 1024 * 1024 } };
    else if (path === '/user/preference-options') body = [{ key: 'travel_style', label: '旅行风格', multi: true, options: ['文化探索', '自然风光', '美食之旅'] }, { key: 'transport', label: '交通偏好', multi: true, options: ['高铁', '公共交通', '自驾', '步行'] }, { key: 'diet', label: '饮食偏好', multi: true, options: ['本地特色', '中餐', '素食'] }, { key: 'pace', label: '旅行节奏', multi: false, options: ['紧凑充实', '适中平衡', '轻松悠闲'] }];
    else if (path === '/user/profile') { body = { preferences: { travel_style: ['文化探索'], transport: ['高铁'], pace: '轻松悠闲' } }; if (controls.profileFailure) status = 503; }
    else if (path === '/user/preferences') body = { status: 'ok' };
    else if (path === '/user/default-origin') body = { place: origin };
    else if (path === '/user/memory/facts' && method === 'GET') { body = { facts, total: facts.length }; if (controls.memoryFailure) status = 503; }
    else if (path === '/user/memory/facts' && method === 'POST') body = { status: 'existing', fact: facts[0] };
    else if (path.startsWith('/user/memory/facts/') && method === 'DELETE') { facts = facts.filter(fact => fact.fact_id !== path.split('/').at(-1)); body = { status: 'deleted' }; }
    else if (path === '/user/memory' && method === 'DELETE') { facts = []; body = { affected_facts: 2 }; }
    else if (path === '/presets' && method === 'GET') body = presets;
    else if (path === '/presets/generate-instructions') { status = 503; body = { detail: 'offline failure' }; }
    else if (path.startsWith('/presets') && method !== 'GET') { status = (method === 'DELETE' ? controls.presetDeleteFailure : controls.presetSaveFailure) ? 503 : 200; body = status === 200 ? { ...presets[5], ...request.postDataJSON?.() } : { detail: 'offline failure' }; }
    else if (path.endsWith('/stats')) body = { total: documents.reduce((sum, doc) => sum + doc.chunk_count, 0), sources: documents.length, source_details: documents };
    else if (path === '/knowledge/collections/travel_knowledge/source') {
      const source = url.searchParams.get('source');
      const document = documents.find(doc => doc.source === source);
      if (method === 'PUT') { if (controls.sourceSaveFailure) status = 503; else if (document) document.content = request.postDataJSON().content; }
      if (method === 'DELETE') { if (controls.sourceDeleteFailure) status = 503; else documents = documents.filter(doc => doc.source !== source); }
      if (method === 'GET' && controls.sourceReadFailure) status = 503;
      body = status === 200 ? document : { detail: 'offline failure' };
    }
    else if (path === '/knowledge/index') { status = controls.textFailure ? 503 : 200; body = { chunks_indexed: 1, collection: 'travel_knowledge' }; }
    else if (path === '/knowledge/upload-file') { status = 503; body = { detail: 'offline failure' }; }
    else if (path === '/product/trip-planner') body = { primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 14000, inspiration_prompts: [] };
    else if (path.endsWith('/weather/refresh')) body = { attempted: false, committed: false, used_previous_values: true, refusal_reason: null, bundle: xianLayoutBundle({ dayCount: 3 }) };
    else if (method !== 'GET') { unexpectedWrites.push(`${method} ${path}`); status = 501; }
    await route.fulfill({ status, json: body });
  });
  return { controls, errors, unexpectedWrites, writes };
}

async function open(page: Page, view: string) {
  await page.goto(`/?view=${view}`);
  await expect(page.getByTestId('surface-loading')).toHaveCount(0);
  await expect(page.locator('.archive-content')).toBeVisible();
}

test('saves the origin through the API and keeps partial resource failures distinct', async ({ page }) => {
  const f = await fixture(page);
  f.controls.memoryFailure = true;
  await open(page, 'user-preferences');
  await expect(page.getByTestId('request-failure-notice')).toBeVisible();
  await expect(page.getByText('还没有旅行记忆。', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '保存出发地', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('常用出发地已保存');
  expect(f.writes.find(write => write.path === '/user/default-origin')).toMatchObject({ method: 'PUT', body: { place: { name: '上海' } } });
  await page.getByRole('button', { name: '美食之旅', exact: true }).click();
  await page.getByRole('button', { name: '保存偏好', exact: true }).click();
  await expect.poll(() => f.writes.find(write => write.path === '/user/preferences')).toMatchObject({ body: { preferences: { travel_style: ['文化探索', '美食之旅'] } } });
  f.controls.memoryFailure = false;
  await page.getByTestId('request-failure-action').click();
  await expect(page.getByTestId('memory-fact')).toHaveCount(2);
  f.controls.profileFailure = true;
  await page.reload();
  await expect(page.getByRole('button', { name: '保存偏好', exact: true })).toBeDisabled();
  expect(f.errors).toEqual([]); expect(f.unexpectedWrites).toEqual([]);
});

test('memory deletion confirms its scope and preserves hand entered preferences', async ({ page }) => {
  const f = await fixture(page);
  await open(page, 'user-preferences');
  const row = page.getByTestId('memory-fact').first();
  await row.getByRole('button', { name: '删除', exact: true }).click();
  await row.getByRole('button', { name: '确认删除', exact: true }).click();
  await expect(page.getByTestId('memory-fact')).toHaveCount(1);
  await page.getByText('记忆如何使用与管理', { exact: true }).click();
  await page.getByTestId('memory-delete-all').click();
  const dialog = page.getByRole('dialog', { name: '删除全部记忆？' });
  await expect(dialog).toContainText('手填偏好和常用出发地保留');
  await expect(dialog).toContainText('手动管理内容');
  await page.getByTestId('memory-delete-all-confirm').click();
  await expect(page.getByText('还没有旅行记忆。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '文化探索', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('textbox', { name: '出发地', exact: true })).toHaveValue('上海');
  expect(f.unexpectedWrites).toEqual([]);
});

test('current results and historical records enter the correct delivery view', async ({ page }) => {
  await fixture(page);
  await open(page, 'trips');
  await expect(page.getByText('不应重复展示的 Markdown 回答')).toHaveCount(0);
  const trip = page.getByTestId('trip-card-A');
  await expect(trip.locator('details')).not.toHaveAttribute('open');
  await expect(page.getByTestId('trip-card-C').getByRole('button', { name: '查看记录', exact: true })).toBeVisible();
  await trip.getByRole('button', { name: '查看行程', exact: true }).click();
  await expect(page.getByTestId('bundle-leaflet-map')).toBeVisible();
  await expect(page.getByText('历史结果 · 只读', { exact: true })).toHaveCount(0);
  await open(page, 'trips');
  await page.getByTestId('trip-card-A').locator('summary').click();
  await page.getByTestId('trip-card-A').getByRole('button', { name: '只读查看', exact: true }).click();
  await expect(page).toHaveURL(/run_id=run-old/);
  await expect(page.getByText('历史结果 · 只读', { exact: true })).toBeVisible();
});

test('style deletion, AI generation and final save failures remain actionable', async ({ page }) => {
  const f = await fixture(page); f.controls.presetDeleteFailure = true; f.controls.presetSaveFailure = true;
  await open(page, 'presets');
  const card = page.getByTestId('preset-card-style-5');
  await card.getByRole('button', { name: '删除这个风格' }).click();
  await card.getByRole('button', { name: '确认删除', exact: true }).click();
  await expect(card.getByRole('alert')).toBeVisible();
  await expect(card).toBeVisible();
  await page.getByRole('button', { name: '创建风格', exact: true }).click();
  await page.locator('#preset-name').fill('城市慢走');
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await page.getByRole('button', { name: 'AI 辅助', exact: true }).click();
  await page.getByRole('textbox', { name: 'AI 辅助描述' }).fill('文化与步行');
  await page.getByRole('button', { name: '生成规划方式', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  await expect.poll(() => f.writes.some(write => write.path === '/presets/generate-instructions')).toBe(true);
  await page.locator('#preset-instructions').fill('每天一个街区，保留休息时间。');
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toHaveCount(0);
  await page.getByRole('button', { name: '创建旅行风格', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  await expect.poll(() => f.writes.some(write => write.path === '/presets' && write.method === 'POST')).toBe(true);
  await expect(page.getByRole('dialog')).toContainText('每天一个街区');
  expect(f.unexpectedWrites).toEqual([]);
});

test('using a style starts a new trip and stale selections are explained', async ({ page }) => {
  await fixture(page);
  await open(page, 'presets');
  await page.getByTestId('preset-card-style-0').getByRole('button', { name: '用于新旅行', exact: true }).click();
  await expect(page).toHaveURL(/view=chat/);
  expect(new URL(page.url()).searchParams.has('session_id')).toBe(false);
  await expect(page.getByTestId('preset-active-chip')).toContainText('深度文化游');
  await page.evaluate(() => localStorage.setItem('journeypilot.active-preset', JSON.stringify({ id: 'missing', name: '失效风格' })));
  await page.reload();
  await expect(page.getByRole('status')).toBeVisible();
  await expect(page.getByTestId('preset-active-chip')).toHaveCount(0);
});

test('source reading, editing and deletion failures retain the document and draft', async ({ page }) => {
  const f = await fixture(page); f.controls.sourceReadFailure = true;
  await open(page, 'knowledge-base');
  await page.getByTestId('knowledge-source-row-京都步行笔记.md').click();
  await expect(page.getByTestId('request-failure-notice')).toBeVisible();
  f.controls.sourceReadFailure = false;
  await page.getByTestId('request-failure-action').click();
  await page.getByRole('button', { name: '编辑正文', exact: true }).click();
  const input = page.getByRole('textbox', { name: '资料正文', exact: true });
  await input.fill('新的步行安排');
  f.controls.sourceSaveFailure = true;
  await page.getByRole('button', { name: '保存正文', exact: true }).click();
  await expect(page.locator('.knowledge-document').getByRole('alert')).toBeVisible();
  await expect(input).toHaveValue('新的步行安排');
  await page.getByTestId('knowledge-source-row-住宿备选.pdf').click();
  await expect(page.getByRole('dialog', { name: '放弃未保存的修改？' })).toBeVisible();
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  f.controls.sourceSaveFailure = false;
  await page.getByRole('button', { name: '保存正文', exact: true }).click();
  await expect(page.getByRole('status')).toBeVisible();
  await page.getByTestId('knowledge-source-row-京都步行笔记.md').click();
  await expect(page.locator('.knowledge-document-content')).toHaveText('新的步行安排');
  f.controls.sourceDeleteFailure = true;
  await page.getByTestId('knowledge-source-delete').click();
  await page.getByTestId('knowledge-source-delete-confirm').click();
  await expect(page.locator('.knowledge-document').getByRole('alert')).toBeVisible();
  await expect(page.locator('.knowledge-document-content')).toHaveText('新的步行安排');
  expect(f.unexpectedWrites).toEqual([]);
});

test('upload limits follow runtime settings and text failures keep their input', async ({ page }) => {
  const f = await fixture(page); f.controls.textFailure = true;
  await open(page, 'knowledge-base');
  await expect(page.getByText(/单份不超过 1 MB/)).toBeVisible();
  const file = page.getByLabel('上传旅行资料', { exact: true });
  await file.setInputFiles({ name: 'too-large.txt', mimeType: 'text/plain', buffer: Buffer.alloc(1024 * 1024 + 1) });
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(file).toHaveValue('');
  expect(f.writes.filter(write => write.path === '/knowledge/upload-file')).toHaveLength(0);
  await file.setInputFiles({ name: 'notes.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('notes') });
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(file).toHaveValue('');
  expect(f.writes.filter(write => write.path === '/knowledge/upload-file')).toHaveLength(0);
  await page.getByRole('button', { name: '添加文本', exact: true }).click();
  await page.getByRole('textbox', { name: '旅行资料正文', exact: true }).fill('保留这份草稿');
  await page.getByRole('button', { name: '添加资料', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  await expect(page.getByRole('textbox', { name: '旅行资料正文', exact: true })).toHaveValue('保留这份草稿');
});
