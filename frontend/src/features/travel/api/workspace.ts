import { type WorkspaceV2MutationRequest, type WorkspaceV2MutationPreviewResponse, type WorkspaceV2MutationResponse, type WorkspaceV2UndoHead, type WorkspaceV2UndoRequest, type WorkspaceV2UndoResponse } from "../types/workspace";
import { fetchJson, SLOW_TIMEOUT_MS, withQuery } from "../../../lib/http";
export async function previewWorkspaceV2Mutation(runId: string, request: WorkspaceV2MutationRequest): Promise<WorkspaceV2MutationPreviewResponse> {
    return fetchJson<WorkspaceV2MutationPreviewResponse>(`/trip-runs/${encodeURIComponent(runId)}/workspace/mutations/preview`, { method: 'POST', body: JSON.stringify(request) }, SLOW_TIMEOUT_MS);
}
export async function applyWorkspaceV2Mutation(runId: string, request: WorkspaceV2MutationRequest): Promise<WorkspaceV2MutationResponse> {
    return fetchJson<WorkspaceV2MutationResponse>(`/trip-runs/${encodeURIComponent(runId)}/workspace/mutations`, { method: 'POST', body: JSON.stringify(request) }, SLOW_TIMEOUT_MS);
}
export async function getWorkspaceV2Mutation(runId: string, mutationId: string, sessionId?: string | null): Promise<WorkspaceV2MutationResponse> {
    return fetchJson<WorkspaceV2MutationResponse>(withQuery(`/trip-runs/${encodeURIComponent(runId)}/workspace/mutations/${encodeURIComponent(mutationId)}`, { session_id: sessionId }));
}
export async function getWorkspaceV2UndoHead(runId: string, sessionId?: string | null): Promise<WorkspaceV2UndoHead> {
    return fetchJson<WorkspaceV2UndoHead>(withQuery(`/trip-runs/${encodeURIComponent(runId)}/workspace/undo-head`, {
        session_id: sessionId,
    }));
}
export async function undoWorkspaceV2Mutation(runId: string, request: WorkspaceV2UndoRequest): Promise<WorkspaceV2UndoResponse> {
    return fetchJson<WorkspaceV2UndoResponse>(`/trip-runs/${encodeURIComponent(runId)}/workspace/undo`, { method: 'POST', body: JSON.stringify(request) }, SLOW_TIMEOUT_MS);
}
