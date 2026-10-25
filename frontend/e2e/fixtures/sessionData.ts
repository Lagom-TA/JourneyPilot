export function sessionSummary(id: string) {
  return { session_id: id, title: `离线会话 ${id}`, status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-25T08:00:00Z', updated_at: '2026-10-25T08:00:00Z' };
}
export function sessionDetail(id: string) {
  return { ...sessionSummary(id), messages: [{ id: `${id}-history`, role: 'assistant', content: `${id} 的历史回答`, display_content: `${id} 的历史回答`, timestamp: '2026-10-25T08:00:00Z' }], next_before: null, has_more: false };
}
export function deliveryBundle() {
  const cost = { known_subtotal_cny: null, estimated_total_cny: null, priced_component_count: 0, budget_relevant_component_count: 0, coverage: 'none', budget_cap_cny: null, budget_status: 'unknown', llm_estimated_total_cny: null };
  return {
    manifest: { contract_version: 'journeypilot.delivery_bundle.v10', run_id: 'run-A', generation_id: 'generation-A', bundle_id: 'bundle-1', workspace_revision: 1, fact_data_revision: 1, weather_data_revision: 1, created_at: '2026-10-25T08:00:00Z' },
    workspace: { contract_version: 'journeypilot.trip_workspace.v10', run_id: 'run-A', generation_id: 'generation-A', workspace_revision: 1,
      itinerary: { itinerary_id: 'itinerary-A', title: '离线旅行交付', destination_ids: [], duration_days: 1, day_plans: [], visit_stops: [], dining_stops: [], lodging_stays: [], transport_legs: [], custom_blocks: [], cost_summary: cost, highlights: [], important_notes: [] },
      fulfillment_summary: { fulfilled: [], deviations: [] }, selection_slots: [], weather_proposal_decisions: [], weather_adjustments: [] },
    report_projection: { source_workspace_revision: 1, source_fact_data_revision: 1, source_weather_data_revision: 1, status: 'ready',
      document: { title: '离线旅行报告', overview: '仅使用本地测试数据', destinations: [], duration_days: 1, cost_summary: cost, cost_coverage_statement: null, days: [], selections: [], weather: [], highlights: [], important_notes: [] }, citations: [], generated_at: '2026-10-25T08:00:00Z' },
    map_projection: { source_workspace_revision: 1, content: { places: [], routes: [] } }, source_index: { source_fact_data_revision: 1, content: { citations: [] } }, coverage_disclosure: { notes: [] }, provider_environment: { sandbox_note: null },
  };
}
