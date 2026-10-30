import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const decision = { route: 'trip_planning', confidence: 1, alternatives: [], signals: [], requires_trip_draft: true, requires_confirmation: false };
const place = (name: string, id: string) => ({ place_id: id, provider: 'osm', kind: 'city', name, display_name: name, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: [] });
const origin = place('上海', 'offline:上海');
const destination = place('杭州', 'offline:杭州');
const party = { adults: 2, children: 0, elderly_companions: true, accessibility_required: false };
const style = { primary: '轻松慢游', secondary_interests: [], source: 'current' };
const budgetQuestion = { id: 'budget_scope', question: '预算包含往返交通吗？', kind: 'single', options: [{ id: 'yes', label: '包含交通' }, { id: 'no', label: '不包含交通' }] };
const mobilityQuestion = { id: 'mobility', question: '长辈爬楼是否受限？', kind: 'single', options: [{ id: 'avoid', label: '需要避免爬楼' }, { id: 'some', label: '可以少量爬楼' }] };
const initial = {
  intake_id: "it_" + "a".repeat(32), intake_revision: 0, raw_input: '带长辈去杭州，预算一万元', route_decision: decision, controlled_identity: null,
  seed_destinations: [], missing_fields: [], ready_to_create: false,
  recognized_requirements: ['带长辈', '预算一万元'], understanding_status: 'ready',
  draft: { origin_query: '上海', destination_queries: ['杭州'], start_date: '2026-11-05', end_date: '2026-11-08', duration_days: 4, party, style, budget_text: '一万元', destination_decided: true, destination_suggestions: [], confirmed_origin: origin, confirmed_destinations: [destination] },
  questions: [budgetQuestion], answers: [], additional_requirements: '',
};

for (const archived of [false, true]) {
 test(`回答后展示新缺口，直到分析完成才进入计划审批${archived ? '（归档历史）' : ''}`, async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => localStorage.setItem('sta_last_session_id', 'multi-round'));
  const pageErrors: string[] = [];
  const escaped: string[] = [];
  const requests: Record<string, any>[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  let pending: any = structuredClone(initial);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) { escaped.push(url.href); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/sessions/multi-round/intake') {
      const submitted = route.request().postDataJSON();
      if (submitted.intake_id !== pending.intake_id || submitted.intake_revision !== pending.intake_revision) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'intake_version_stale', message: '旅行需求已更新，请刷新后重新核对。' } }) });
      pending = { ...submitted, intake_revision: pending.intake_revision + 1 };
      return json(pending);
    }
    if (path === '/chat-stream') {
      const body = route.request().postDataJSON();
      requests.push(body);
      let events: unknown[];
      if (requests.length === 1) {
        pending = archived
          ? { ...body.guided_intake, intake_revision: body.guided_intake.intake_revision + 1, controlled_identity: body.controlled_trip_identity, questions: [mobilityQuestion], answers: [], archived_answers: [{ question_id: 'budget_scope', question: budgetQuestion.question, answer: '包含交通' }], ready_to_create: false }
          : { ...body.guided_intake, intake_revision: body.guided_intake.intake_revision + 1, controlled_identity: body.controlled_trip_identity, questions: [budgetQuestion, mobilityQuestion], ready_to_create: false };
        events = [{ type: 'guided_intake', session_id: 'multi-round', guided_intake: pending }, { type: 'chat_complete' }];
      } else {
        pending = null;
        events = [
          { type: 'chat_start', session_id: 'multi-round', run_id: 'multi-round-run', message_id: 'assistant-plan', route_decision: decision },
          { type: 'approval_gate_raised', run_id: 'multi-round-run', gate: 'plan', run_status: 'awaiting_input', payload: { gate: 'plan', revision: 0, approval_token: 'offline-token', revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'], plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '研究无障碍出行和适合长辈的路线' } }] }, plan_text: '**研究计划**：研究无障碍出行和适合长辈的路线。', recognized_requirements: { hard: [], preferences: [], attention: [] }, unresolved_requirement_ids: [] } },
          { type: 'chat_complete', run_id: 'multi-round-run', run_status: 'awaiting_input' },
        ];
      }
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
    }
    const summary = { session_id: 'multi-round', title: '杭州旅行', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-30', updated_at: '2026-10-30' };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/user/sessions/multi-round') return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === '/trip-runs/multi-round-run/events') return json({ run_id: 'multi-round-run', requested_after_sequence: 0, replay_floor_sequence: 0, latest_sequence: 0, next_after_sequence: 0, window_expired: false, current_bundle_id: null, run_status: 'awaiting_input', events: [] });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'slow', label: '轻松慢游', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  await page.goto('/');
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await page.getByRole('button', { name: '包含交通', exact: true }).click();
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect(page.getByText('长辈爬楼是否受限？', { exact: true })).toBeVisible();
  await expect(page.getByTestId('guided-intake-collapsed')).toHaveCount(0);
  await expect(page.getByTestId('trip-brief-plan-gate')).toHaveCount(0);
  if (archived) await expect(page.locator('.travel-intake-answer').filter({ hasText: '预算包含往返交通吗？' })).toContainText('包含交通');
  expect(requests).toHaveLength(1);
  mkdirSync('../output/polish/20261030-1416-clarify-before-plan', { recursive: true });
  await page.screenshot({ path: '../output/polish/20261030-1416-clarify-before-plan/second-question.png', fullPage: true });
  await page.getByRole('button', { name: '需要避免爬楼', exact: true }).click();
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1].guided_intake.answers.map((answer: { question_id: string }) => answer.question_id)).toEqual(archived ? ['mobility'] : ['budget_scope', 'mobility']);
  if (archived) expect(requests[1].guided_intake.archived_answers[0].answer).toBe('包含交通');
  await page.screenshot({ path: '../output/polish/20261030-1416-clarify-before-plan/plan-gate.png', fullPage: true });
  expect(pageErrors).toEqual([]);
  expect(escaped).toEqual([]);
 });
}
