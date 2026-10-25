import { type JsonObject } from "../../../lib/json";
export interface MemoryDeleteOptions {
    request_id?: string | null;
    reason?: string;
    clear_auto_portrait?: boolean;
    clear_graph?: boolean;
    clear_session_anchors?: boolean;
}
export interface MemoryDeleteAllOptions {
    request_id?: string | null;
    reason?: string;
    clear_auto_portrait?: boolean;
    clear_graph?: boolean;
    clear_session_anchors?: boolean;
}
export interface MemoryRetentionCleanupRequest {
    request_id?: string | null;
    reason?: string;
    limit?: number;
}
export interface MemoryDeletionResponse {
    request_id: string;
    scope: string;
    category: string | null;
    fact_id: string | null;
    status: string;
    affected_facts: number;
    affected_entities: number;
    affected_relations: number;
    affected_profiles: number;
    affected_session_anchors: number;
    boundary: JsonObject;
    created_at: string;
}
export type MemoryFactSource = 'manual' | 'auto';
export interface MemoryFactItem {
    fact_id: string;
    content: string;
    category: string | null;
    importance: number;
    source: MemoryFactSource;
    created_at: string;
    expires_at: string;
}
export interface MemoryFactListResponse {
    facts: MemoryFactItem[];
    total: number;
}
export interface AddMemoryFactResponse {
    status: 'created' | 'existing';
    fact: MemoryFactItem;
}
