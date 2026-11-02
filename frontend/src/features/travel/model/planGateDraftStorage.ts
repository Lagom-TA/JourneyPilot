const PREFIX = 'journeypilot.plan-gate-draft';

export function planGateDraftKey(sessionId: string | null, runId: string, token?: string): string | null {
    if (!sessionId || !runId || !token) return null;
    try {
        return [PREFIX, sessionId, runId, token].map(encodeURIComponent).join(':');
    } catch {
        return null;
    }
}

export function readPlanGateDraft(key: string | null): { value: string; available: boolean } {
    if (!key) return { value: '', available: false };
    try {
        return { value: (sessionStorage.getItem(key) || '').slice(0, 500), available: true };
    } catch {
        return { value: '', available: false };
    }
}

export function writePlanGateDraft(key: string | null, value: string): boolean {
    if (!key) return false;
    try {
        if (value) sessionStorage.setItem(key, value.slice(0, 500));
        else sessionStorage.removeItem(key);
        return true;
    } catch {
        return false;
    }
}
