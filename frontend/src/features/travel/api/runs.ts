import { type TripRunControlRequest, type TripRunControlResponse, type TripRunListResponse, type TripRunDetailResponse, type TripRunEventWindowResponse } from "../types/runs";
import { fetchJson, withQuery } from "../../../lib/http";
export async function controlTripRun(runId: string, request: TripRunControlRequest): Promise<TripRunControlResponse> {
    return fetchJson<TripRunControlResponse>(`/trip-runs/${encodeURIComponent(runId)}/control`, {
        method: 'POST',
        body: JSON.stringify(request),
    });
}
export async function listTripRuns(options?: {
    sessionId?: string;
    mode?: 'deep' | 'fast';
    limit?: number;
}): Promise<TripRunListResponse> {
    return fetchJson<TripRunListResponse>(withQuery('/trip-runs', {
        session_id: options?.sessionId,
        mode: options?.mode,
        limit: options?.limit ?? 80,
    }));
}
export async function getTripRunDetail(runId: string, options?: {
    sessionId?: string | null;
}): Promise<TripRunDetailResponse> {
    return fetchJson<TripRunDetailResponse>(withQuery(`/trip-runs/${encodeURIComponent(runId)}`, {
        event_limit: 80,
        session_id: options?.sessionId,
    }));
}
export async function getTripRunEventWindow(runId: string, options: {
    sessionId?: string | null;
    afterSequence: number;
    limit?: number;
}): Promise<TripRunEventWindowResponse> {
    return fetchJson<TripRunEventWindowResponse>(withQuery(`/trip-runs/${encodeURIComponent(runId)}/events`, {
        session_id: options.sessionId,
        after_sequence: options.afterSequence,
        limit: options.limit ?? 200,
    }));
}
