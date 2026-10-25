import { createContext, useContext } from "react";
import { type AppState, type AppAction } from "./state";
import { type ActiveStreamHandle, type SessionRuntimeSnapshot } from "../session/runtimeSnapshot";
export const AppContext = createContext<{
    state: AppState;
    dispatch: React.Dispatch<AppAction>;
    activeStreamAbortRef: React.MutableRefObject<AbortController | null>;
    activeStreamRef: React.MutableRefObject<ActiveStreamHandle | null>;
    currentStateRef: React.MutableRefObject<AppState>;
    sessionRuntimeCacheRef: React.MutableRefObject<Map<string, SessionRuntimeSnapshot>>;
} | null>(null);
export function useApp() {
    const ctx = useContext(AppContext);
    if (!ctx)
        throw new Error('useApp must be used within AppProvider');
    return ctx;
}
