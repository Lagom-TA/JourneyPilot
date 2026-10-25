import { type VisitStop, type DiningStop, type LodgingPriceKind, type LodgingAvailabilityStatus, type TransportLeg, type TransportMode, type TransportEndpoint, type TransportSegment, type DayPlanV2, type EntityRef } from "./entities";
import { type CostCoverageSummary } from "./report";
export type EvidenceBasis = 'cited_source' | 'public_reference' | 'reference_service';
export interface EntityIntentExplanation {
    label: string;
    explanation: string;
    evidence_basis: 'verified_fact' | 'supported_description' | 'planning_judgment';
}
export interface IntentExplanationRecord extends EntityIntentExplanation {
    intent_id: string;
}
export interface PublicRequirementFulfillment {
    requirement_id: string;
    summary: string;
    status: 'satisfied' | 'partially_satisfied' | 'unsatisfied' | 'unverifiable';
    explanation: string;
}
export interface PublicFulfillmentSummary {
    fulfilled: PublicRequirementFulfillment[];
    deviations: PublicRequirementFulfillment[];
}
export interface PublicVisitStop {
    type: 'visit_stop';
    item_id: string;
    day_id: string;
    place_id: string;
    name: string;
    address: string | null;
    latitude: number | null;
    longitude: number | null;
    planned_start: string | null;
    planned_end: string | null;
    duration_minutes: number;
    estimated_cost_cny: number | null;
    selection_reason: string;
    visit_type: VisitStop['visit_type'];
    opening_window: string | null;
    reservation_required: boolean | null;
    visit_highlights: string[];
    intent_explanations: EntityIntentExplanation[];
    evidence_basis: EvidenceBasis;
}
export interface PublicDiningStop {
    type: 'dining_stop';
    item_id: string;
    day_id: string;
    place_id: string;
    name: string;
    address: string | null;
    latitude: number | null;
    longitude: number | null;
    planned_start: string | null;
    planned_end: string | null;
    duration_minutes: number;
    estimated_cost_cny: number | null;
    selection_reason: string;
    meal_type: DiningStop['meal_type'];
    cuisine_types: string[];
    average_spend_cny: number | null;
    recommended_dishes: string[];
    reservation_required: boolean | null;
    opening_window: string | null;
    dining_reminders: string[];
    intent_explanations: EntityIntentExplanation[];
    evidence_basis: EvidenceBasis;
}
export interface PublicLodgingStay {
    type: 'lodging_stay';
    stay_id: string;
    place_id: string;
    name: string;
    check_in_date: string;
    check_out_date: string;
    check_in_time: string | null;
    check_out_time: string | null;
    nights: number;
    room_type: string | null;
    nightly_price_cny: number | null;
    total_price_cny: number | null;
    price_kind: LodgingPriceKind;
    availability_status: LodgingAvailabilityStatus;
    address: string;
    selection_reason: string;
    intent_explanations: EntityIntentExplanation[];
    evidence_basis: EvidenceBasis;
}
export interface PublicTransportLeg {
    type: 'transport_leg';
    transport_leg_id: string;
    transport_class: TransportLeg['transport_class'];
    selected_mode: TransportMode;
    from_endpoint: TransportEndpoint;
    to_endpoint: TransportEndpoint;
    departure_at: string | null;
    arrival_at: string | null;
    duration_minutes: number | null;
    distance_meters: number | null;
    total_cost_cny: number | null;
    transfer_count: number;
    segments: TransportSegment[];
    booking_status: TransportLeg['booking_status'];
    route_status: TransportLeg['route_status'];
    mode_preference: {
        locked_mode: TransportMode | null;
        excluded_modes: TransportMode[];
    };
    intent_explanations: EntityIntentExplanation[];
    evidence_basis: EvidenceBasis;
    is_micro_transport: boolean;
}
export interface PublicCustomBlock {
    type: 'custom_block';
    item_id: string;
    day_id: string;
    title: string;
    note: string | null;
    planned_start: string | null;
    planned_end: string | null;
    duration_minutes: number | null;
}
export interface PublicStructuredItineraryV2 {
    itinerary_id: string;
    title: string;
    destination_ids: string[];
    duration_days: number;
    day_plans: DayPlanV2[];
    visit_stops: PublicVisitStop[];
    dining_stops: PublicDiningStop[];
    lodging_stays: PublicLodgingStay[];
    transport_legs: PublicTransportLeg[];
    custom_blocks: PublicCustomBlock[];
    cost_summary: CostCoverageSummary;
    highlights: string[];
    important_notes: string[];
}
export interface SelectionOption {
    option_id: string;
    rank: number;
    selected: boolean;
    recommended: boolean;
    selection_reasons: string[];
    tradeoff: string | null;
    comparison_facts: string[];
    availability_status: 'confirmed' | 'needs_confirmation';
}
export type SelectionSlotType = 'lodging' | 'dining' | 'visit' | 'transport';
export interface SelectionSlot {
    selection_slot_id: string;
    slot_type: SelectionSlotType;
    target_entity_id: string;
    context: Record<string, unknown>;
    options: SelectionOption[];
    status: 'researching' | 'ready' | 'refreshing' | 'needs_user_decision';
}
export interface PersonalizationInfluence {
    influence_id: string;
    target_ref: EntityRef | {
        selection_slot_id: string;
    };
    intent_id: string;
    constraint_id: string | null;
    effect: 'candidate_filter' | 'option_ranking' | 'selection_reason' | 'schedule_rule' | 'output_requirement';
    source_kind: 'current_request' | 'saved_preference' | 'trip_context';
    display_text: string;
}
