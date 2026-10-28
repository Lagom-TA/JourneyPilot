import { useEffect, useRef } from "react";
import { useApp } from "../state/AppContext";
import { isActiveView } from "../state/state";
import { useSessionManager } from "../session/useSessionManager";
export function ViewUrlSync() {
    const { state, dispatch, currentStateRef } = useApp();
    const { openSession } = useSessionManager();
    const activeView = state.activeView;
    const fromPopRef = useRef(false);
    const initializedRef = useRef(false);
    useEffect(() => {
        if (fromPopRef.current) {
            fromPopRef.current = false;
            return;
        }
        const url = new URL(window.location.href);
        if (url.searchParams.get('view') === activeView) {
            initializedRef.current = true;
            return;
        }
        url.searchParams.set('view', activeView);
        const next = `${url.pathname}${url.search}${url.hash}`;
        if (!initializedRef.current) {
            initializedRef.current = true;
            window.history.replaceState(null, '', next);
        }
        else {
            window.history.pushState(null, '', next);
        }
    }, [activeView]);
    useEffect(() => {
        const handlePopState = () => {
            const params = new URLSearchParams(window.location.search);
            const view = params.get('view');
            const nextView = isActiveView(view) ? view : 'chat';
            fromPopRef.current = true;
            dispatch({ type: 'SET_ACTIVE_VIEW', payload: nextView });
            const sessionId = params.get('session_id');
            const runId = params.get('run_id') ?? undefined;
            if (nextView === 'chat' && sessionId) {
                const current = currentStateRef.current;
                if (current.currentSessionId !== sessionId || (runId && current.currentTripRunId !== runId) || (!runId && current.currentTripRunReadOnly)) {
                    void openSession(sessionId, runId);
                }
            }
        };
        window.addEventListener('popstate', handlePopState);
        return () => window.removeEventListener('popstate', handlePopState);
    }, [currentStateRef, dispatch, openSession]);
    return null;
}
