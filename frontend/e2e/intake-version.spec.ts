import { expect, test } from '@playwright/test';

const decision = { route: 'trip_planning', confidence: 1, alternatives: [], signals: [], requires_trip_draft: true, requires_confirmation: false };
const place = (name: string) => ({ place_id: `offline:${name}`, provider: 'osm', kind: 'city', name, display_name: name, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: [] });
const initial = {
  intake_id: "it_" + "b".repeat(32), intake_revision: 0, raw_input: '带长辈去杭州，预算一万元', route_decision: decision, controlled_identity: null,
  seed_destinations: [], missing_fields: [], ready_to_create: false, recognized_requirements: [], understanding_status: 'ready',
  draft: { origin_query: '上海', destination_queries: ['杭州'], start_date: '2026-11-05', end_date: '2026-11-08', duration_days: 4, party: { adults: 2, children: 0, elderly_companions: true, accessibility_required: false }, style: { primary: '轻松慢游', secondary_interests: [], source: 'current' }, budget_text: '', destination_decided: true, destination_suggestions: [], confirmed_origin: place('上海'), confirmed_destinations: [place('杭州')] },
  questions: [{ id: 'budget_scope', question: '预算包含往返交通吗？', kind: 'single', options: [{ id: 'yes', label: '包含交通' }, { id: 'no', label: '不包含交通' }] }],
  answers: [], additional_requirements: '',
};

for (const replacedIntake of [false, true]) {
 test(`旧页面不覆盖新版回答，也不能静默开始${replacedIntake ? '（新草稿版本重用）' : ''}`, async ({ context, page }) => {
  let pending: any = structuredClone(initial);
  const chatRequests: unknown[] = [];
  const escaped: string[] = [];
  await context.addInitScript(() => localStorage.setItem('sta_last_session_id', 'intake-versions'));
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) { escaped.push(url.href); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/sessions/intake-versions/intake') {
      const body = route.request().postDataJSON();
      if (body.intake_id !== pending.intake_id || body.intake_revision !== pending.intake_revision) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'intake_version_stale', message: '旅行需求已更新，请刷新后重新核对。', current_revision: pending.intake_revision } }) });
      pending = { ...body, intake_revision: pending.intake_revision + 1 };
      return json(pending);
    }
    if (path === '/chat-stream') { chatRequests.push(route.request().postDataJSON()); return json({}); }
    const summary = { session_id: 'intake-versions', title: '杭州旅行', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-30', updated_at: '2026-10-30' };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/user/sessions/intake-versions') return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'slow', label: '轻松慢游', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  const other = await context.newPage();
  await Promise.all([page.goto('/'), other.goto('/')]);
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await expect(other.getByTestId('guided-intake')).toBeVisible();
  await other.getByRole('button', { name: '不包含交通', exact: true }).click();
  await expect.poll(() => pending.intake_revision).toBe(1);
  if (replacedIntake) pending = { ...pending, intake_id: 'it_' + 'd'.repeat(32), intake_revision: 0 };
  await page.getByRole('button', { name: '包含交通', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('旅行需求已在其他页面更新');
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  expect(chatRequests).toEqual([]);
  expect(pending.answers[0].selected_option_ids).toEqual(['no']);
  expect(escaped).toEqual([]);
 });
}
