import { type MemoryDeleteOptions, type MemoryDeletionResponse, type MemoryDeleteAllOptions, type MemoryRetentionCleanupRequest, type MemoryFactListResponse, type AddMemoryFactResponse } from "../types/memory";
import { fetchJson } from "../../../lib/http";
export async function deleteMemoryFact(factId: string, options: MemoryDeleteOptions = {}): Promise<MemoryDeletionResponse> {
    return fetchJson<MemoryDeletionResponse>(`/user/memory/facts/${encodeURIComponent(factId)}`, {
        method: 'DELETE',
        body: JSON.stringify(options),
    });
}
export async function deleteAllMemory(options: MemoryDeleteAllOptions = {}): Promise<MemoryDeletionResponse> {
    return fetchJson<MemoryDeletionResponse>('/user/memory', {
        method: 'DELETE',
        body: JSON.stringify(options),
    });
}
export async function cleanupExpiredMemory(request: MemoryRetentionCleanupRequest = {}): Promise<MemoryDeletionResponse> {
    return fetchJson<MemoryDeletionResponse>('/user/memory/retention/cleanup', {
        method: 'POST',
        body: JSON.stringify(request),
    });
}
export async function listMemoryFacts(): Promise<MemoryFactListResponse> {
    return fetchJson<MemoryFactListResponse>('/user/memory/facts');
}
export async function addMemoryFact(content: string): Promise<AddMemoryFactResponse> {
    return fetchJson<AddMemoryFactResponse>('/user/memory/facts', {
        method: 'POST',
        body: JSON.stringify({ content }),
    });
}
