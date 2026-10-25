import { type StructuredItineraryV2, type UserInputAnchor, type CustomBlock, type TransportMode } from "./entities";
import { type RecommendationCatalog, type IntentContractSnapshot, type IntentCoverageReport, type CandidateSelectionPlan } from "./research";
import { type SelectionSlot, type PersonalizationInfluence } from "./itinerary";
import { type PublicDeliveryBundle } from "./delivery";
export const TRIP_WORKSPACE_CONTRACT_VERSION = 'journeypilot.trip_workspace.v10' as const;
export interface CompositionMutation {
    mutation_id: string;
    generation_id: string;
    mutation_type: 'drop' | 'move' | 'replace' | 'backfill' | 'reorder' | 'time_adjust';
    reason_code: string;
    source_entity_ids: string[];
    target_entity_ids: string[];
    affected_intent_ids: string[];
    affected_rule_ids: string[];
    hard_rules_revalidated: boolean;
    created_by: 'deterministic_pruner' | 'anchor_backfill' | 'slot_backfill' | 'composition_repair' | 'user_edit';
}
export interface TripWorkspaceV2 {
    contract_version: typeof TRIP_WORKSPACE_CONTRACT_VERSION;
    run_id: string;
    generation_id: string;
    workspace_revision: number;
    itinerary: StructuredItineraryV2;
    recommendation_catalog: RecommendationCatalog;
    intent_contract_snapshot: IntentContractSnapshot;
    intent_coverage_report: IntentCoverageReport | null;
    composition_mutations: CompositionMutation[];
    candidate_selection_plan: CandidateSelectionPlan;
    user_input_anchors: UserInputAnchor[];
    selection_slots: SelectionSlot[];
    personalization_influences: PersonalizationInfluence[];
    weather_proposal_decisions: Array<{
        proposal_id: string;
        decision: 'applied' | 'dismissed';
    }>;
}
export type WorkspaceV2MutationOperation = {
    type: 'select_option';
    selection_slot_id: string;
    option_id: string;
} | {
    type: 'move_timeline_item';
    item_id: string;
    to_day_id: string;
    before_entry_id?: string | null;
} | {
    type: 'update_stop_schedule';
    item_id: string;
    planned_start?: string | null;
    planned_end?: string | null;
    duration_minutes?: number | null;
} | {
    type: 'create_custom_block';
    block: CustomBlock;
    before_entry_id?: string | null;
} | {
    type: 'update_custom_block';
    item_id: string;
    title?: string;
    note?: string | null;
    planned_start?: string | null;
    planned_end?: string | null;
    duration_minutes?: number | null;
} | {
    type: 'delete_custom_block';
    item_id: string;
} | {
    type: 'delete_transport_leg';
    transport_leg_id: string;
} | {
    type: 'set_transport_mode';
    transport_leg_id: string;
    selected_mode: TransportMode;
    lock_mode?: boolean;
} | {
    type: 'update_transport_mode_preference';
    transport_leg_id: string;
    locked_mode?: TransportMode | null;
    excluded_modes?: TransportMode[] | null;
} | {
    type: 'delete_lodging_stay';
    stay_id: string;
} | {
    type: 'apply_weather_adjustment';
    proposal_id: string;
} | {
    type: 'dismiss_weather_adjustment';
    proposal_id: string;
};
export interface WorkspaceV2MutationRequest {
    session_id: string | null;
    mutation_id: string;
    base_bundle_id: string;
    base_workspace_revision: number;
    base_fact_data_revision: number;
    base_weather_data_revision: number;
    operation: WorkspaceV2MutationOperation;
}
export interface WorkspaceV2MutationPreviewResponse {
    mutation_id: string;
    allowed: boolean;
    changed: boolean;
    requires_confirmation: boolean;
    impacts: Array<{
        kind: 'total_cost';
        delta_cny: number;
        summary: string;
    }>;
}
export interface WorkspaceV2MutationResponse {
    mutation_id: string;
    changed: boolean;
    idempotent_replay: boolean;
    bundle: PublicDeliveryBundle;
}
export interface WorkspaceV2UndoHead {
    available: boolean;
    mutation_id: string | null;
    label: string | null;
}
export interface WorkspaceV2UndoRequest {
    session_id: string | null;
    undo_id: string;
    undo_of_mutation_id: string;
    base_bundle_id: string;
    base_workspace_revision: number;
    base_fact_data_revision: number;
    base_weather_data_revision: number;
}
export interface WorkspaceV2UndoResponse {
    undo_id: string;
    idempotent_replay: boolean;
    bundle: PublicDeliveryBundle;
}
