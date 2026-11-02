import { type TripReportProjection, type MapProjection, type PublicCitationProjection } from "./report";
import { type PublicStructuredItinerary, type SelectionSlot } from "./itinerary";
import { type PublicWeatherAdjustment } from "./weather";
export interface DeliveryRevisionManifest {
    run_id: string;
    generation_id: string;
    bundle_id: string;
    workspace_revision: number;
    fact_data_revision: number;
    weather_data_revision: number;
    created_at: string;
}
export interface PublicDeliveryBundle {
    manifest: DeliveryRevisionManifest;
    workspace: PublicTripWorkspace;
    report_projection: TripReportProjection;
    map_projection: MapProjection;
    source_index: {
        source_fact_data_revision: number;
        content: {
            citations: PublicCitationProjection[];
        };
    };
    provider_environment: {
        sandbox_note: string | null;
    };
}
export interface PublicTripWorkspace {
    run_id: string;
    generation_id: string;
    workspace_revision: number;
    itinerary: PublicStructuredItinerary;
    selection_slots: SelectionSlot[];
    weather_adjustments: PublicWeatherAdjustment[];
}
export function isPublicDeliveryBundle(value: unknown): value is PublicDeliveryBundle {
    if (!value || typeof value !== 'object')
        return false;
    const bundle = value as Partial<PublicDeliveryBundle>;
    const manifest = bundle.manifest;
    const workspace = bundle.workspace;
    return Boolean(manifest
        && typeof manifest.run_id === 'string'
        && typeof manifest.bundle_id === 'string'
        && workspace
        && workspace.run_id === manifest.run_id
        && workspace.generation_id === manifest.generation_id
        && workspace.workspace_revision === manifest.workspace_revision
        && Array.isArray(workspace.itinerary?.day_plans)
        && Array.isArray(workspace.selection_slots)
        && Array.isArray(workspace.weather_adjustments)
        && bundle.report_projection
        && bundle.map_projection
        && bundle.source_index);
}
