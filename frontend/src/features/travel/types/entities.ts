import { type IntentExplanationRecord } from "./itinerary";
export type EntityType = 'visit_stop' | 'dining_stop' | 'lodging_stay' | 'transport_leg' | 'transport_segment' | 'custom_block' | 'weather_day';
export interface EntityRef {
    entity_type: EntityType;
    entity_id: string;
}
export interface EntityLineage {
    lineage_kind: 'candidate_entity' | 'authored_entity' | 'reference_entity';
    research_packet_id: string | null;
    candidate_id: string | null;
    selection_slot_id: string | null;
    fact_assertion_ids: string[];
    source_record_ids: string[];
    planning_decision_ids: string[];
    weather_impact_ids: string[];
    personalization_influence_ids: string[];
}
export type TransportMode = 'flight' | 'high_speed_rail' | 'train' | 'coach' | 'ferry' | 'metro' | 'bus' | 'tram' | 'taxi' | 'ride_hailing' | 'drive' | 'bike' | 'walk' | 'other';
export interface TransportEndpoint {
    name: string;
    place_id: string | null;
    station_code: string | null;
    latitude: number | null;
    longitude: number | null;
}
export interface TransportSegment {
    segment_id: string;
    mode: TransportMode;
    from_endpoint: TransportEndpoint;
    to_endpoint: TransportEndpoint;
    departure_at: string | null;
    arrival_at: string | null;
    duration_minutes: number | null;
    distance_meters: number | null;
    operator_name: string | null;
    service_number: string | null;
    line_name: string | null;
    cost_cny: number | null;
}
export interface TransportLeg {
    type: 'transport_leg';
    transport_leg_id: string;
    transport_class: 'long_distance' | 'public_transit' | 'flexible';
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
    booking_status: 'not_required' | 'recommended' | 'required' | 'booked' | 'unknown';
    route_status: 'pending' | 'ready' | 'unavailable';
    mode_preference: {
        locked_mode: TransportMode | null;
        excluded_modes: TransportMode[];
    };
    intent_explanations: IntentExplanationRecord[];
    lineage: EntityLineage;
}
interface ScheduledStopBase {
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
    intent_explanations: IntentExplanationRecord[];
    lineage: EntityLineage;
}
export interface VisitStop extends ScheduledStopBase {
    type: 'visit_stop';
    visit_type: 'attraction' | 'experience' | 'culture' | 'shopping' | 'nature' | 'other';
    opening_window: string | null;
    reservation_required: boolean | null;
    visit_highlights: string[];
}
export interface DiningStop extends ScheduledStopBase {
    type: 'dining_stop';
    meal_type: 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'other';
    cuisine_types: string[];
    average_spend_cny: number | null;
    recommended_dishes: string[];
    reservation_required: boolean | null;
    opening_window: string | null;
    dining_reminders: string[];
}
export type LodgingPriceKind = 'reference_estimate' | 'live_quote';
export type LodgingAvailabilityStatus = 'confirmed' | 'needs_confirmation' | 'unavailable';
export interface LodgingStay {
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
    intent_explanations: IntentExplanationRecord[];
    lineage: EntityLineage;
}
export interface CustomBlock {
    type: 'custom_block';
    item_id: string;
    day_id: string;
    title: string;
    note: string | null;
    planned_start: string | null;
    planned_end: string | null;
    duration_minutes: number | null;
}
export interface DayPlanV2 {
    day_id: string;
    day: number;
    date: string | null;
    destination_id: string | null;
    theme: string;
    timeline: Array<{
        entry_id: string;
        entity_type: EntityType;
        entity_id: string;
        projection_role: 'full' | 'departure' | 'arrival' | 'check_in' | 'check_out';
    }>;
    estimated_cost_cny: number | null;
}
