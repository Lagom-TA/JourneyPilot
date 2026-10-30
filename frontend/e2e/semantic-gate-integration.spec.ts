import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const decision = { route: 'trip_planning', confidence: 1, alternatives: [], signals: [], requires_trip_draft: true, requires_confirmation: false };
const place = (name: string) => ({ place_id: `offline:${name}`, provider: 'osm', kind: 'city', name, display_name: name, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: [] });
const party = { adults: 2, children: 0, elderly_companions: false, accessibility_required: false };
const style = { primary: '经典均衡', secondary_interests: [], source: 'current' };
const identity = { origin: place('上海'), destinations: [place('杭州')], start_date: '2026-11-05', end_date: '2026-11-07', party, style };
const intake = {
  intake_id: 'it_' + 'a'.repeat(32), intake_revision: 1,
  raw_input: '去杭州，不喝咖啡', route_decision: decision, controlled_identity: identity,
  seed_destinations: [], missing_fields: [], ready_to_create: true, recognized_requirements: [], understanding_status: 'ready',
  draft: { origin_query: '上海', destination_queries: ['杭州'], start_date: identity.start_date, end_date: identity.end_date, duration_days: 3, party, style, budget_text: '', destination_decided: true, destination_suggestions: [], confirmed_origin: identity.origin, confirmed_destinations: identity.destinations },
  questions: [], answers: [], archived_answers: [], additional_requirements: '',
};
const semantic = {
  gate: 'plan', phase: 'semantics', challenge_id: 'challenge_' + 'a'.repeat(64), revision: 1, approval_token: 'semantic-token',
  assertions: [{
    assertion_id: 'coffee', source_kind: 'current_request', context: '去杭州，不喝咖啡', quote: '咖啡', object_label: '咖啡', domain_label: '餐饮', allowed_decisions: ['avoid', 'historical', 'unknown'],
    execution: {
      requirement_id: 'constraint_coffee', requirement_type: 'constraint', kind: 'dietary_restriction', target: 'dietary_restriction',
      polarity: 'exclude', strength: 'hard', value: { value: '不喝咖啡', params: {} },
      applies_to: ['全体同行：2 位成人、0 位儿童'], scope: 'dietary_restriction', public_summary: '不喝咖啡',
    },
  }],
};
const plan = {
  gate: 'plan', revision: 1, approval_token: 'plan-token', revision_limit: 2,
  decision_options: ['approve', 'supplement', 'cancel'],
  plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '研究杭州餐饮并避开咖啡' } }] },
  plan_text: '**研究计划**：研究杭州餐饮并避开咖啡。', recognized_requirements: { hard: [], preferences: [] },
};

test('必要问答只提交回答，不展示参数确认页', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('sta_last_session_id', 'semantic-integration'));
  const requests: Record<string, any>[] = [];
  const escaped: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let pending: any = structuredClone(intake);
  let currentGate: any = semantic;
  let hasRun = false;
  let semanticAttempts = 0;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) { escaped.push(url.href); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/sessions/semantic-integration/intake') { pending = route.request().postDataJSON(); return json(pending); }
    if (path === '/chat-stream') {
      const body = route.request().postDataJSON(); requests.push(body);
      const events: unknown[] = [{ type: 'chat_start', session_id: 'semantic-integration', run_id: 'semantic-run', message_id: 'assistant', route_decision: decision }];
      if (!hasRun) { hasRun = true; pending = null; }
      else {
        semanticAttempts += 1;
        if (semanticAttempts === 1) {
          currentGate = plan;
        }
      }
      events.push({ type: 'approval_gate_raised', run_id: 'semantic-run', gate: 'plan', run_status: 'awaiting_input', payload: currentGate });
      events.push({ type: 'chat_complete', run_id: 'semantic-run', run_status: 'awaiting_input' });
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
    }
    const summary = { session_id: 'semantic-integration', title: '杭州旅行', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-30', updated_at: '2026-10-30' };
    const run = { run_id: 'semantic-run', session_id: summary.session_id, status: 'awaiting_input', mode: 'deep', controlled_trip_identity: identity };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/user/sessions/semantic-integration') return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    if (path === '/trip-runs') return json({ runs: hasRun ? [run] : [], total: hasRun ? 1 : 0 });
    if (path === '/trip-runs/semantic-run') return json({ run, state: { pending_user_choice: { type: 'approval_gate', gate: 'plan', payload: currentGate } }, controlled_trip_identity: identity });
    if (path === '/trip-runs/semantic-run/events') return json({ run_id: run.run_id, requested_after_sequence: 0, replay_floor_sequence: 0, latest_sequence: 0, next_after_sequence: 0, window_expired: false, current_bundle_id: null, run_status: 'awaiting_input', events: [] });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  await page.goto('/');
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect(page.getByTestId('semantic-requirement-gate')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '补充必要信息', exact: true })).toBeVisible();
  await expect(page.getByText('全部执行参数', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '确认并开始生成' })).toHaveCount(0);
  mkdirSync('../output/polish/20261030-1416-clarify-before-plan', { recursive: true });
  await page.screenshot({ path: '../output/polish/20261030-1416-clarify-before-plan/necessary-question.png', fullPage: true });
  await page.getByLabel('你的回答').fill('不喝咖啡');
  await page.getByTestId('plan-gate-supplement').click();
  await expect(page.getByRole('heading', { name: '确认旅行需求', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '确认并开始生成' })).toBeVisible();
  await page.screenshot({ path: '../output/polish/20261030-1416-clarify-before-plan/final-plan-gate.png', fullPage: true });
  expect(requests).toHaveLength(2);
  expect(requests[1].gate_decision).toEqual({ action: 'supplement', approval_token: 'semantic-token', content: '不喝咖啡' });
  expect(requests[1].gate_decision.semantic_confirmation).toBeUndefined();
  expect(errors).toEqual([]);
  expect(escaped).toEqual([]);
});
