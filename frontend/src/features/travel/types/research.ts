import { type VisitStop, type DiningStop, type LodgingPriceKind, type LodgingAvailabilityStatus, type TransportLeg, type TransportMode, type TransportEndpoint, type TransportSegment } from "./entities";
import { type SourceRecord, type FactAssertion, type FieldProvenance } from "./facts";
export const RECOMMENDATION_CATALOG_CONTRACT_VERSION = 'journeypilot.recommendation_catalog.v6' as const;
export const RESEARCH_PACKET_CONTRACT_VERSION = 'journeypilot.research_packet.v5' as const;
interface CandidateBase {
    candidate_id: string;
    research_packet_id: string;
    destination_id: string;
    fact_assertion_ids: string[];
    source_record_ids: string[];
    field_paths: string[];
    active_constraint_ids: string[];
    constraint_evaluations: Array<{
        constraint_id: string;
        status: 'passed' | 'failed' | 'unknown';
        fact_assertion_ids: string[];
        reason_code: string | null;
    }>;
    weather_sensitivity: {
        exposure: 'indoor' | 'outdoor' | 'mixed';
        rain_sensitivity: 'none' | 'low' | 'high';
        heat_sensitivity: 'none' | 'low' | 'high';
        cold_sensitivity: 'none' | 'low' | 'high';
        wind_sensitivity: 'none' | 'low' | 'high';
        requires_clear_visibility: boolean;
    };
    selection_reasons: string[];
    tradeoff: string;
    planning_decision_ids: string[];
    weather_impact_ids: string[];
    personalization_influence_ids: string[];
    freshness_status: 'current' | 'refreshing' | 'stale';
    observed_at: string | null;
    expires_at: string | null;
}
export type ResearchCandidate = CandidateBase & ({
    candidate_kind: 'visit';
    place_id: string;
    name: string;
    address: string;
    visit_type: VisitStop['visit_type'];
    recommended_duration_minutes: number;
    estimated_cost_cny: number | null;
    opening_window: string | null;
    reservation_required: boolean | null;
    highlights: string[];
} | {
    candidate_kind: 'dining';
    place_id: string;
    branch_name: string;
    address: string;
    meal_types: DiningStop['meal_type'][];
    cuisine_types: string[];
    average_spend_cny: number | null;
    recommended_dishes: string[];
    opening_window: string | null;
    reservation_required: boolean | null;
    availability_status: 'confirmed' | 'needs_confirmation' | 'unavailable';
} | {
    candidate_kind: 'lodging';
    place_id: string;
    property_name: string;
    address: string;
    check_in_date: string;
    check_out_date: string;
    nights: number;
    room_type: string | null;
    nightly_price_cny: number | null;
    total_price_cny: number | null;
    price_kind: LodgingPriceKind;
    facilities: string[];
    anchor_travel_minutes: Record<string, number>;
    availability_status: LodgingAvailabilityStatus;
} | {
    candidate_kind: 'transport';
    route_id: string;
    transport_class: TransportLeg['transport_class'];
    selected_mode: TransportMode;
    from_endpoint: TransportEndpoint;
    to_endpoint: TransportEndpoint;
    departure_at: string | null;
    arrival_at: string | null;
    duration_minutes: number;
    distance_meters: number | null;
    total_cost_cny: number | null;
    segments: TransportSegment[];
    booking_status: TransportLeg['booking_status'];
});
export type ResearchDomain = 'visit' | 'dining' | 'lodging' | 'local_transport' | 'long_distance_transport';
export interface CandidateDiscoveryRecord {
    candidate_id: string;
    generation_id: string;
    query_ids: string[];
    intent_ids: string[];
    origins: Array<'intent_query' | 'structural_query' | 'generic_fallback' | 'targeted_repair' | 'composer_authored_fallback'>;
    provider_audit_ids: string[];
    discovered_at_rounds: number[];
}
export interface CandidateIntentMatch {
    candidate_id: string;
    intent_id: string;
    status: 'matched' | 'not_matched' | 'violated' | 'unknown' | 'not_applicable';
    score: number | null;
    method: 'deterministic' | 'semantic_batch_evaluation';
    supporting_fact_assertion_ids: string[];
    supporting_source_record_ids: string[];
    reason_code: string;
    public_reason: string | null;
}
export interface CandidateRankingScore {
    candidate_id: string;
    generation_id: string;
    hard_eligible: boolean;
    hard_violation_intent_ids: string[];
    matched_intent_ids: string[];
    unknown_intent_ids: string[];
    high_priority_coverage_score: number;
    semantic_fit: number;
    evidence_confidence: number;
    budget_fit: number;
    weather_fit: number;
    constraint_fit: number;
    regional_fit: number;
    diversity_potential: number;
    generic_fallback_penalty: number;
    redundancy_penalty: number;
    travel_cost_penalty: number;
    ranking_tuple: number[];
    policy_version: string;
}
export interface ResearchPacket {
    contract_version: typeof RESEARCH_PACKET_CONTRACT_VERSION;
    research_packet_id: string;
    run_id: string;
    generation_id: string;
    intent_spec_revision: number;
    research_query_plan_id: string;
    executed_query_ids: string[];
    candidate_discovery_records: CandidateDiscoveryRecord[];
    task_id: string;
    worker_kind: 'destination_researcher' | 'accommodation_researcher' | 'transport_researcher';
    constraint_pack_revision: number;
    fact_data_revision: number;
    query_context: Record<string, unknown>;
    candidates: ResearchCandidate[];
    source_records: SourceRecord[];
    fact_assertions: FactAssertion[];
    field_provenance: FieldProvenance[];
    generated_at: string;
}
export interface RecommendationCatalog {
    contract_version: typeof RECOMMENDATION_CATALOG_CONTRACT_VERSION;
    generation_id: string;
    intent_spec_revision: number;
    research_query_plan_id: string;
    fact_data_revision: number;
    weather_data_revision: number;
    research_packets: ResearchPacket[];
    admission_results: Array<{
        candidate_id: string;
        selection_slot_id: string | null;
        status: 'passed' | 'insufficient_for_admission';
        checked_constraint_ids: string[];
        missing_field_paths: string[];
        fit_scores: {
            budget_fit: number;
            weather_fit: number;
            constraint_fit: number;
        };
        evaluated_fact_revision: number;
        evaluated_weather_revision: number;
        weather_impact_ids: string[];
    }>;
    candidate_discovery_records: CandidateDiscoveryRecord[];
    candidate_intent_matches: CandidateIntentMatch[];
    candidate_ranking_scores: CandidateRankingScore[];
}
export interface CandidateSelectionPlan {
    schema_version: 'journeypilot.candidate_selection.v2';
    selection_plan_id: string;
    generation_id: string;
    intent_spec_revision: number;
    catalog_revision: number;
    entries: Array<{
        candidate_id: string;
        domain: ResearchDomain;
        destination_id: string;
        role: 'required_primary' | 'primary' | 'alternative' | 'fallback';
        rank: number;
        covered_intent_ids: string[];
        selection_reasons: string[];
        eligible_for_composition: boolean;
    }>;
    covered_intent_ids: string[];
    uncovered_intent_ids: string[];
    selection_policy: {
        mode: 'deterministic' | 'explore';
        selection_seed: number | null;
        alternative_count: number;
        diversity_strength: number;
        avoid_previous_candidate_ids: string[];
        preferred_theme_clusters: string[];
        policy_version: string;
    };
    content_hash: string;
}
export interface IntentContractSnapshot {
    schema_version: 'journeypilot.intent_contract_snapshot.v1';
    generation_id: string;
    intent_spec_revision: number;
    objective_summary: string;
    requirements: Array<{
        intent_id: string;
        kind: string;
        target: string;
        strength: 'hard' | 'soft' | 'informational';
        verification_mode: 'deterministic' | 'semantic' | 'mixed';
        impact_stages: string[];
        public_summary: string;
    }>;
    conflict_summaries: string[];
    content_hash: string;
}
export interface IntentCoverageReport {
    schema_version: 'journeypilot.intent_coverage.v1';
    coverage_report_id: string;
    generation_id: string;
    intent_spec_revision: number;
    workspace_revision: number;
    items: Array<{
        intent_id: string;
        status: 'satisfied' | 'partially_satisfied' | 'unsatisfied' | 'unverifiable' | 'unsupported' | 'conflicted';
        public_explanation: string;
        blocking: boolean;
    }>;
    hard_satisfaction_rate: number;
    soft_coverage_rate: number;
    blocking_gap_ids: string[];
    content_hash: string;
}
