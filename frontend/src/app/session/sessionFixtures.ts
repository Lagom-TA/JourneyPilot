import { DELIVERY_BUNDLE_CONTRACT_VERSION, type PublicDeliveryBundle } from '../../features/travel/types/delivery';
import { TRIP_WORKSPACE_CONTRACT_VERSION } from '../../features/travel/types/workspace';
import type { SessionDetail, SessionSummary } from '../../features/chat/types/sessions';

export function sessionSummary(id: string): SessionSummary {
  return { session_id: id, title: `离线会话 ${id}`, status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-25T08:00:00Z', updated_at: '2026-10-25T08:00:00Z' };
}
export function sessionDetail(id: string): SessionDetail {
  return { ...sessionSummary(id), messages: [{ id: `${id}-history`, role: 'assistant', content: `${id} 的历史回答`, display_content: `${id} 的历史回答`, timestamp: '2026-10-25T08:00:00Z' }], next_before: null, has_more: false };
}
export function deliveryBundle(revision = 1): PublicDeliveryBundle {
  const cost = { known_subtotal_cny: null, estimated_total_cny: null, priced_component_count: 0, budget_relevant_component_count: 0, coverage: 'none' as const, budget_cap_cny: null, budget_status: 'unknown' as const, llm_estimated_total_cny: null };
  return {
    manifest: { contract_version: DELIVERY_BUNDLE_CONTRACT_VERSION, run_id: 'run-A', generation_id: 'generation-A', bundle_id: `bundle-${revision}`, workspace_revision: revision, fact_data_revision: revision, weather_data_revision: revision, created_at: '2026-10-25T08:00:00Z' },
    workspace: { contract_version: TRIP_WORKSPACE_CONTRACT_VERSION, run_id: 'run-A', generation_id: 'generation-A', workspace_revision: revision,
      itinerary: { itinerary_id: 'itinerary-A', title: '离线旅行交付', destination_ids: [], duration_days: 1, day_plans: [], visit_stops: [], dining_stops: [], lodging_stays: [], transport_legs: [], custom_blocks: [], cost_summary: cost, highlights: [], important_notes: [] },
      selection_slots: [], weather_proposal_decisions: [], weather_adjustments: [] },
    report_projection: { source_workspace_revision: revision, source_fact_data_revision: revision, source_weather_data_revision: revision, status: 'ready',
      document: { title: '离线旅行报告', overview: '仅使用本地测试数据', destinations: [], duration_days: 1, cost_summary: cost, cost_coverage_statement: null, days: [], selections: [], weather: [], highlights: [], important_notes: [] }, citations: [], generated_at: '2026-10-25T08:00:00Z' },
    map_projection: { source_workspace_revision: revision, content: { places: [], routes: [] } },
    source_index: { source_fact_data_revision: revision, content: { citations: [] } }, provider_environment: { sandbox_note: null },
  };
}
