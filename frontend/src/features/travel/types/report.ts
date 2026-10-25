import { type EntityRef, type TransportMode, type TransportLeg, type TransportEndpoint, type TransportSegment } from "./entities";
import { type EvidenceBasis, type SelectionSlotType } from "./itinerary";
export interface PublicCitationProjection {
    citation_id: string;
    entity_ref: EntityRef;
    field_paths: string[];
    fact_status: 'verified' | 'refreshing' | 'stale' | 'conflict' | 'missing';
    supported_values: Array<{
        label: string;
        value: unknown;
        unit: string | null;
        currency: string | null;
    }>;
    sources: Array<{
        source_record_id: string;
        source_kind: 'external_web' | 'external_tool' | 'rag_chunk';
        title: string;
        public_excerpt: string;
        canonical_url: string | null;
        retrieved_at: string;
        observed_at: string | null;
    }>;
}
export interface PublicBlockPresentation {
    entry_id: string;
    display_title: string;
    node_summary: string | null;
    node_role: 'place' | 'movement' | 'arrival' | 'departure';
    transport_mode: TransportMode | null;
    time_label: string | null;
    duration_label: string | null;
    price_label: string | null;
    facts: string[];
    notes: string[];
    segment_lines: string[];
}
export type PublicReportBlockDetails = PublicBlockPresentation & {
    [key: string]: unknown;
};
interface PublicReportBlockBase {
    entity_ref: EntityRef;
    day_id: string | null;
    projection_role: 'full' | 'departure' | 'arrival' | 'check_in' | 'check_out';
    title: string;
    summary: string;
    details: PublicReportBlockDetails;
    citation_ids: string[];
}
export interface PublicReportEntityBlock extends PublicReportBlockBase {
    entity_kind: 'visit' | 'dining' | 'lodging' | 'transport';
    evidence_basis: EvidenceBasis;
}
export interface PublicReportCustomBlock extends PublicReportBlockBase {
    entity_kind: 'custom';
}
export type PublicReportBlock = PublicReportEntityBlock | PublicReportCustomBlock;
export interface TripReportProjection {
    source_workspace_revision: number;
    source_fact_data_revision: number;
    source_weather_data_revision: number;
    status: 'pending' | 'building' | 'ready' | 'stale' | 'failed';
    document: {
        title: string;
        overview: string;
        destinations: Array<{
            destination_id: string;
            display_name: string;
        }>;
        duration_days: number;
        cost_summary: CostCoverageSummary;
        cost_coverage_statement: string | null;
        days: Array<{
            day_id: string;
            day: number;
            date: string | null;
            destination_id: string;
            destination_name: string;
            theme: string;
            blocks: PublicReportBlock[];
        }>;
        selections: Array<{
            selection_slot_id: string;
            slot_type: SelectionSlotType;
            context: Record<string, unknown>;
            status: 'ready' | 'needs_user_decision';
            options: Array<{
                option_id: string;
                name: string;
                rank: number;
                selected: boolean;
                recommended: boolean;
                selection_reasons: string[];
                tradeoff: string | null;
                comparison_facts: string[];
                availability_status: 'confirmed' | 'needs_confirmation';
                citation_ids: string[];
            }>;
        }>;
        weather: Array<{
            destination_id: string;
            destination_name: string;
            date: string;
            data_kind: 'forecast' | 'seasonal_baseline' | 'unavailable';
            observed_at: string | null;
            weather_data_state: 'current' | 'historical';
            condition_label: string | null;
            high_c: number | null;
            low_c: number | null;
            precipitation_probability_pct: number | null;
            wind_speed_kph: number | null;
            citation_ids: string[];
        }>;
        highlights: string[];
        important_notes: string[];
    } | null;
    citations: PublicCitationProjection[];
    generated_at: string | null;
}
export interface CostCoverageSummary {
    known_subtotal_cny: number | null;
    estimated_total_cny: number | null;
    priced_component_count: number;
    budget_relevant_component_count: number;
    coverage: 'none' | 'partial' | 'complete';
    budget_cap_cny: number | null;
    budget_status: 'unknown' | 'within_cap' | 'over_cap';
    llm_estimated_total_cny: number | null;
}
export interface MapProjection {
    source_workspace_revision: number;
    content: {
        places: Array<{
            entity_ref: EntityRef;
            name: string;
            place_id: string;
            latitude: number | null;
            longitude: number | null;
            citation_ids: string[];
        }>;
        routes: Array<{
            entity_ref: EntityRef;
            transport_class: TransportLeg['transport_class'];
            selected_mode: TransportMode;
            route_status: TransportLeg['route_status'];
            from_endpoint: TransportEndpoint;
            to_endpoint: TransportEndpoint;
            segments: TransportSegment[];
            citation_ids: string[];
        }>;
    };
}
