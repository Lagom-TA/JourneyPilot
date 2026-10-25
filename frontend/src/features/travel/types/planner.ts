export type PlaceKind = 'city' | 'administrative_area' | 'island' | 'scenic_area' | 'airport' | 'train_station' | 'country' | 'poi' | 'hotel' | 'restaurant';
export type JourneyRoute = 'trip_planning' | 'destination_discovery' | 'fast_answer' | 'trip_refinement';
export type TripSupplementCategory = 'food' | 'transport' | 'accommodation' | 'pace' | 'must_do' | 'other';
export type PlanGateDecisionAction = 'approve' | 'edit' | 'supplement' | 'cancel';
export interface PlaceIdentity {
    place_id: string;
    provider: 'osm' | 'amap' | 'manual_verified';
    kind: PlaceKind;
    name: string;
    display_name: string;
    country_code: string;
    latitude: number;
    longitude: number;
    admin_path: string[];
}
export interface RouteDecision {
    route: JourneyRoute;
    confidence: number;
    alternatives: Array<{
        route: JourneyRoute;
        confidence: number;
    }>;
    signals: string[];
    requires_trip_draft: boolean;
    requires_confirmation?: boolean;
}
export interface ControlledTripIdentity {
    origin: PlaceIdentity;
    destinations: PlaceIdentity[];
    start_date: string;
    end_date: string;
    party: {
        adults: number;
        children: number;
        elderly_companions: boolean;
        accessibility_required: boolean;
    };
    style: {
        primary: string;
        secondary_interests: string[];
        source: 'current' | 'suggested';
    };
}
export interface PlannerOption {
    id: string;
    label: string;
    inference_keywords: string[];
    is_default: boolean;
}
export interface TripPlannerConfiguration {
    primary_styles: PlannerOption[];
    secondary_interests: PlannerOption[];
    default_adults: number;
    default_children: number;
    default_elderly_companions: boolean;
    default_accessibility_required: boolean;
    max_secondary_interests: number;
    inspiration_rotation_ms: number;
    inspiration_prompts: string[];
}
export interface GuidedIntakeState {
    raw_input: string;
    route_decision: RouteDecision;
    controlled_identity: ControlledTripIdentity | null;
    seed_destinations?: PlaceIdentity[];
    missing_fields: Array<'origin' | 'destinations' | 'dates' | 'party' | 'style' | 'place_confirmation'>;
    ready_to_create: boolean;
}
