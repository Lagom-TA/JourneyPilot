import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const decision = { route: 'trip_planning', confidence: 1, alternatives: [], signals: [], requires_trip_draft: true, requires_confirmation: false };
const place = (name: string, id: string) => ({ place_id: id, provider: 'osm', kind: 'city', name, display_name: name, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: [] });
const origin = place('上海', 'offline:上海');
const destination = place('杭州', 'offline:杭州');
const party = { adults: 2, children: 0, elderly_companions: true, accessibility_required: false };
const style = { primary: '轻松慢游', secondary_interests: [], source: 'current' };
const identity = { origin, destinations: [destination], start_date: '2026-11-05', end_date: '2026-11-08', party, style };
const intake = {
  intake_id: 'it_' + 'c'.repeat(32), intake_revision: 1,
  raw_input: '带长辈旅行，但行动限制不明确', route_decision: decision, controlled_identity: identity,
  seed_destinations: [], missing_fields: [], ready_to_create: true,
  recognized_requirements: ['带长辈'], understanding_status: 'ready',
  draft: { origin_query: '上海', destination_queries: ['杭州'], start_date: '2026-11-05', end_date: '2026-11-08', duration_days: 4, party, style, budget_text: '', destination_decided: true, destination_suggestions: [], confirmed_origin: origin, confirmed_destinations: [destination] },
  questions: [], answers: [], additional_requirements: '',
};
const clarify = {
  gate: 'plan', revision: 0, revision_limit: 1, revision_limit_reached: false,
  approval_token: 'questions-version', decision_options: ['supplement', 'cancel'],
  plan: { steps: [] }, plan_text: '**需要先补充的信息**\n- 请说明「长辈行动限制」的具体要求。',
  recognized_requirements: { hard: [], preferences: [] },
};
const clarifySecond = {
  ...clarify,
  approval_token: 'questions-version-2',
  plan_text: '**需要先补充的信息**\n- 请说明「每天步行距离」的具体要求。',
};
const plan = {
  gate: 'plan', revision: 0, revision_limit: 1, revision_limit_reached: false,
  approval_token: 'plan-version', decision_options: ['approve', 'supplement', 'cancel'],
  plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '研究无障碍路线' } }] },
  plan_text: '**研究计划**：研究无障碍路线。', recognized_requirements: { hard: [], preferences: [] },
};

test('归一化发现未决要求时先追问；刷新后仍须回答，再显示计划', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => localStorage.setItem('sta_last_session_id', 'pre-plan-clarification'));
  const calls: Record<string, any>[] = [];
  const escaped: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let pending: any = structuredClone(intake);
  let currentGate = clarify;
  let hasRun = false;
  const run = { run_id: 'clarify-run', session_id: 'pre-plan-clarification', status: 'awaiting_input', mode: 'deep', controlled_trip_identity: identity };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) { escaped.push(url.href); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/sessions/pre-plan-clarification/intake') { pending = route.request().postDataJSON(); return json(pending); }
    if (path === '/chat-stream') {
      const body = route.request().postDataJSON();
      calls.push(body);
      if (!hasRun) { hasRun = true; pending = null; }
      else { currentGate = calls.length === 2 ? clarifySecond : plan; }
      const events = [
        { type: 'chat_start', session_id: 'pre-plan-clarification', run_id: run.run_id, message_id: 'assistant', route_decision: decision },
        { type: 'approval_gate_raised', run_id: run.run_id, gate: 'plan', run_status: 'awaiting_input', payload: currentGate },
        { type: 'chat_complete', run_id: run.run_id, run_status: 'awaiting_input' },
      ];
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
    }
    const summary = { session_id: 'pre-plan-clarification', title: '杭州旅行', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-30', updated_at: '2026-10-30' };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/user/sessions/pre-plan-clarification') return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    if (path === '/trip-runs') return json({ runs: hasRun ? [run] : [], total: hasRun ? 1 : 0 });
    if (path === '/trip-runs/clarify-run') return json({ run, state: { pending_user_choice: { type: 'approval_gate', gate: 'plan', payload: currentGate } }, controlled_trip_identity: identity });
    if (path === '/trip-runs/clarify-run/events') return json({ run_id: run.run_id, requested_after_sequence: 0, replay_floor_sequence: 0, latest_sequence: 0, next_after_sequence: 0, window_expired: false, current_bundle_id: null, run_status: 'awaiting_input', events: [] });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'slow', label: '轻松慢游', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  await page.goto('/');
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect(page.getByRole('heading', { name: '补充必要信息' })).toBeVisible();
  await expect(page.getByText('请说明「长辈行动限制」的具体要求。')).toBeVisible();
  await expect(page.getByRole('button', { name: '确认并开始生成' })).toHaveCount(0);
  await expect(page.getByText('本次会这样研究')).toHaveCount(0);
  mkdirSync('../output/polish/20261030-1416-clarify-before-plan', { recursive: true });
  await page.screenshot({ path: '../output/polish/20261030-1416-clarify-before-plan/unresolved-question.png', fullPage: true });

  await page.getByLabel('你的回答').fill('长辈需要无障碍交通，请避免长楼梯');
  await page.reload();
  await expect(page.getByRole('heading', { name: '补充必要信息' })).toBeVisible();
  await expect(page.getByRole('button', { name: '确认并开始生成' })).toHaveCount(0);
  await expect(page.getByLabel('你的回答')).toHaveValue('长辈需要无障碍交通，请避免长楼梯');
  await page.getByRole('button', { name: '提交回答并继续整理' }).click();
  await expect(page.getByText('请说明「每天步行距离」的具体要求。')).toBeVisible();
  await expect(page.getByLabel('你的回答')).toHaveValue('');
  await expect(page.getByRole('heading', { name: '补充必要信息' })).toBeFocused();
  await page.getByLabel('你的回答').fill('每天步行不超过三公里');
  await page.getByRole('button', { name: '提交回答并继续整理' }).click();
  await expect(page.getByRole('heading', { name: '确认旅行需求', exact: true })).toBeVisible();
  await expect(page.getByText('研究无障碍路线。')).toBeVisible();
  await expect(page.getByRole('button', { name: '确认并开始生成' })).toBeVisible();
  expect(calls).toHaveLength(3);
  expect(calls[1].gate_decision).toMatchObject({ action: 'supplement', approval_token: 'questions-version', content: '长辈需要无障碍交通，请避免长楼梯' });
  expect(calls[2].gate_decision).toMatchObject({ action: 'supplement', approval_token: 'questions-version-2', content: '每天步行不超过三公里' });
  expect(escaped).toEqual([]);
  expect(errors).toEqual([]);
});
