import { type PublicDeliveryBundle } from "./delivery";
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
