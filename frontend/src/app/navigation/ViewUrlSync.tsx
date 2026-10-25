import { useEffect, useRef } from "react";
import { useApp } from "../state/AppContext";
import { isActiveView } from "../state/state";
export function ViewUrlSync() {
    const { state, dispatch } = useApp();
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
            const v = new URLSearchParams(window.location.search).get('view');
            const nextView = isActiveView(v) ? v : 'chat';
            fromPopRef.current = true;
            dispatch({ type: 'SET_ACTIVE_VIEW', payload: nextView });
        };
        window.addEventListener('popstate', handlePopState);
        return () => window.removeEventListener('popstate', handlePopState);
    }, [dispatch]);
    return null;
}
