import { type TransportMode, type EntityRef } from "./entities";
import { type PublicDeliveryBundle } from "./delivery";
export const WEATHER_SNAPSHOT_CONTRACT_VERSION = 'journeypilot.weather_context_snapshot.v2' as const;
export type WeatherAdjustmentOperation = {
    type: 'reschedule_item';
    item_id: string;
    expected_planned_start: string | null;
    expected_planned_end: string | null;
    planned_start: string;
    planned_end: string;
} | {
    type: 'select_option';
    selection_slot_id: string;
    expected_option_id: string | null;
    option_id: string;
} | {
    type: 'replace_visit_candidate';
    item_id: string;
    expected_candidate_id: string;
    candidate_id: string;
} | {
    type: 'set_transport_mode';
    transport_leg_id: string;
    expected_mode: TransportMode;
    selected_mode: TransportMode;
} | {
    type: 'add_buffer';
    target_entity_id: string;
    day_id: string;
    block_id: string;
    duration_minutes: number;
};
export interface WeatherAdjustmentProposal {
    proposal_id: string;
    date: string;
    base_workspace_revision: number;
    base_weather_data_revision: number;
    severity: 'medium' | 'high';
    summary: string;
    weather_impact_ids: string[];
    fact_assertion_ids: string[];
    operations: WeatherAdjustmentOperation[];
    cost_delta_cny: number | null;
    time_delta_minutes: number | null;
}
export interface WeatherContextSnapshot {
    contract_version: typeof WEATHER_SNAPSHOT_CONTRACT_VERSION;
    weather_data_revision: number;
    trip_start_date: string;
    trip_end_date: string;
    days: Array<{
        destination_id: string;
        date: string;
        timezone: string | null;
        latitude: number;
        longitude: number;
        data_kind: 'forecast' | 'seasonal_baseline' | 'unavailable';
        condition_code: number | null;
        condition_label: string | null;
        high_c: number | null;
        low_c: number | null;
        apparent_high_c: number | null;
        precipitation_probability_pct: number | null;
        precipitation_mm: number | null;
        wind_speed_kph: number | null;
        wind_gust_kph: number | null;
        hourly_windows: Array<{
            start_at: string;
            end_at: string;
            precipitation_probability_pct: number | null;
            apparent_temperature_c: number | null;
            wind_speed_kph: number | null;
        }>;
        alert_ids: string[];
        fact_assertion_ids: string[];
    }>;
    coverage: Array<{
        destination_id: string;
        start_date: string;
        end_date: string;
        status: 'complete' | 'partial' | 'unavailable';
        available_dates: string[];
        unavailable_dates: string[];
    }>;
    impacts: Array<{
        weather_impact_id: string;
        date: string;
        target_ref: EntityRef | {
            selection_slot_id: string;
        } | {
            transport_leg_id: string;
        };
        condition_type: 'rain' | 'heat' | 'cold' | 'wind' | 'thunderstorm' | 'snow' | 'visibility';
        severity: 'low' | 'medium' | 'high';
        action: 'keep' | 'move_time' | 'rerank' | 'replace' | 'change_transport' | 'add_buffer' | 'require_plan_b';
        fact_assertion_ids: string[];
        affected_constraint_ids: string[];
        data_kind: 'forecast' | 'seasonal_baseline';
        trigger_code: string;
    }>;
    adjustment_proposals: WeatherAdjustmentProposal[];
    retrieved_at: string;
}
export interface PublicWeatherAdjustment {
    proposal_id: string;
    date: string;
    severity: 'medium' | 'high';
    summary: string;
    cost_delta_cny: number | null;
    time_delta_minutes: number | null;
    status: 'pending' | 'applied' | 'dismissed';
}
export interface WeatherBundleRefreshRequest {
    session_id: string | null;
    refresh_id: string;
    base_bundle_id: string;
    base_workspace_revision: number;
    base_fact_data_revision: number;
    base_weather_data_revision: number;
}
export interface WeatherBundleRefreshResponse {
    refresh_id: string;
    attempted: boolean;
    committed: boolean;
    used_previous_values: boolean;
    refusal_reason: string | null;
    bundle: PublicDeliveryBundle;
}
