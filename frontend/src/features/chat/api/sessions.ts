import { type SessionSummary, type SessionDetail, type SessionTurnPage } from "../types/sessions";
import { fetchJson, LLM_TIMEOUT_MS } from "../../../lib/http";
export async function listSessions(): Promise<SessionSummary[]> {
    return fetchJson<SessionSummary[]>('/user/sessions');
}
export async function getSessionDetail(sessionId: string): Promise<SessionDetail> {
    return fetchJson<SessionDetail>(`/user/sessions/${encodeURIComponent(sessionId)}`);
}
export async function getSessionTurns(sessionId: string, beforeTurn?: string | null): Promise<SessionTurnPage> {
    const query = beforeTurn ? `?before_turn=${encodeURIComponent(beforeTurn)}` : '';
    return fetchJson<SessionTurnPage>(`/sessions/${encodeURIComponent(sessionId)}/turns${query}`);
}
export async function deleteSession(sessionId: string): Promise<void> {
    await fetchJson<{
        status?: string;
    }>(`/user/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
}
export async function renameSession(sessionId: string, title: string): Promise<SessionSummary> {
    return fetchJson<SessionSummary>(`/user/sessions/${encodeURIComponent(sessionId)}`, { method: 'PATCH', body: JSON.stringify({ title }) });
}
export async function compactSession(sessionId: string) {
    return fetchJson<import('../types/sessions').ContextCompactionPayload>(`/sessions/${encodeURIComponent(sessionId)}/compact`, {
        method: 'POST',
    }, LLM_TIMEOUT_MS);
}
