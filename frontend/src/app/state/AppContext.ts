import { createContext, useContext } from "react";
import { type AppState, type AppAction } from "./state";
import { type ActiveStreamHandle, type SessionRuntimeSnapshot } from "../session/runtimeSnapshot";
import { type PendingFollowups } from "../session/pendingFollowups";
export const AppContext = createContext<{
    state: AppState;
    dispatch: React.Dispatch<AppAction>;
    activeStreamsRef: React.MutableRefObject<Map<string, ActiveStreamHandle>>;
    currentStateRef: React.MutableRefObject<AppState>;
    sessionRuntimeCacheRef: React.MutableRefObject<Map<string, SessionRuntimeSnapshot>>;
    pendingFollowups: PendingFollowups;
    setPendingFollowups: React.Dispatch<React.SetStateAction<PendingFollowups>>;
    pendingFollowupsRef: React.MutableRefObject<PendingFollowups>;
} | null>(null);
export function useApp() {
    const ctx = useContext(AppContext);
    if (!ctx)
        throw new Error('useApp must be used within AppProvider');
    return ctx;
}
