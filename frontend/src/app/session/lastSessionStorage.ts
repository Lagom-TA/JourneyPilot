const LAST_SESSION_KEY = 'journeypilot.last-session-id';
export function getLastSession(): string | null {
    try {
        return localStorage.getItem(LAST_SESSION_KEY);
    }
    catch {
        return null;
    }
}
export function setLastSession(sessionId: string | null): void {
    try {
        if (!sessionId)
            localStorage.removeItem(LAST_SESSION_KEY);
        else
            localStorage.setItem(LAST_SESSION_KEY, sessionId);
    }
    catch {
        // 本地存储不可用时仍可继续使用当前会话。
    }
}
