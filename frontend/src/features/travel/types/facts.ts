import { type EntityRef } from "./entities";
export const FACT_SNAPSHOT_CONTRACT_VERSION = 'journeypilot.fact_store_snapshot.v4' as const;
export interface SourceRecord {
    source_record_id: string;
    source_kind: 'external_web' | 'external_tool' | 'rag_chunk';
    title: string;
    provider_name: string;
    canonical_url: string | null;
    public_excerpt: string;
    published_at: string | null;
    retrieved_at: string;
    observed_at: string | null;
    effective_from: string | null;
    effective_to: string | null;
    provider_valid_until: string | null;
    content_hash: string;
    snapshot: Record<string, unknown>;
    lifecycle_status: 'active' | 'superseded' | 'withdrawn' | 'rejected';
    tool_audit_id: string | null;
    cache_provenance: {
        origin: 'live' | 'provider_snapshot_cache';
        provider_name: string;
        tool_name: string;
        cache_key_digest: string;
        content_hash: string;
        observed_at: string;
        retrieved_at: string;
        provider_valid_until: string | null;
        cache_valid_until: string;
        provider_contract_version: string;
        payload_schema_version: string;
    } | null;
}
export interface FactAssertion {
    fact_assertion_id: string;
    entity_ref: EntityRef;
    field_path: string;
    asserted_value: unknown;
    unit: string | null;
    currency: string | null;
    criticality: 'execution_critical' | 'decision_critical' | 'auxiliary';
    status: 'verified' | 'refreshing' | 'stale' | 'conflict' | 'missing' | 'superseded';
    observed_at: string | null;
    effective_from: string | null;
    effective_to: string | null;
    expires_at: string | null;
    source_links: Array<{
        source_record_id: string;
        relation: 'supports' | 'qualifies' | 'contradicts';
        source_locator: string;
    }>;
    supersedes_assertion_ids: string[];
}
export interface FieldProvenance {
    origin: 'external_fact' | 'planning_decision' | 'deterministic_computation' | 'user_input';
    entity_ref: EntityRef;
    field_path: string;
    reference_ids: string[];
}
export interface FactStoreSnapshot {
    contract_version: typeof FACT_SNAPSHOT_CONTRACT_VERSION;
    fact_data_revision: number;
    source_records: SourceRecord[];
    fact_assertions: FactAssertion[];
    field_provenance: FieldProvenance[];
}
