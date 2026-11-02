export type EntityType = 'visit_stop' | 'dining_stop' | 'lodging_stay' | 'transport_leg' | 'transport_segment' | 'custom_block' | 'weather_day';
export interface EntityRef {
    entity_type: EntityType;
    entity_id: string;
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
    path?: Array<{ latitude: number; longitude: number }>;
    departure_at: string | null;
    arrival_at: string | null;
    duration_minutes: number | null;
    distance_meters: number | null;
    operator_name: string | null;
    service_number: string | null;
    line_name: string | null;
    cost_cny: number | null;
}
export type LodgingPriceKind = 'reference_estimate' | 'live_quote';
export type LodgingAvailabilityStatus = 'confirmed' | 'needs_confirmation' | 'unavailable';
export type VisitType = 'attraction' | 'experience' | 'culture' | 'shopping' | 'nature' | 'other';
export type MealType = 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'other';
export type TransportClass = 'long_distance' | 'public_transit' | 'flexible';
export type BookingStatus = 'not_required' | 'recommended' | 'required' | 'booked' | 'unknown';
export type RouteStatus = 'pending' | 'ready' | 'unavailable';
