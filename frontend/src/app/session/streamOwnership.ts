import { type Dispatch, type MutableRefObject } from "react";
import { appReducer } from "../state/appReducer";
import { type AppAction, type AppState } from "../state/state";
import { createSessionRuntimeSnapshot, type ActiveStreamHandle, type SessionRuntimeSnapshot } from "./runtimeSnapshot";
export function createStreamOwnership(streamToken: string, startSessionId: string | null, startEpoch: number, initialRunId: string | null, ownedController: AbortController | null, activeStreamRef: MutableRefObject<ActiveStreamHandle | null>, currentStateRef: MutableRefObject<AppState>, sessionRuntimeCacheRef: MutableRefObject<Map<string, SessionRuntimeSnapshot>>, dispatch: Dispatch<AppAction>) {
    const identity = { sessionId: startSessionId, runId: initialRunId };
    const isCurrentStream = () => activeStreamRef.current?.token === streamToken;
    const isStreamVisible = () => {
        if (!isCurrentStream())
            return false;
        const current = currentStateRef.current;
        if (identity.sessionId) {
            return current.currentSessionId === identity.sessionId || (!startSessionId && current.conversationEpoch === startEpoch);
        }
        if (startSessionId)
            return current.currentSessionId === startSessionId;
        return current.conversationEpoch === startEpoch;
    };
    const reduceHiddenRuntime = (action: AppAction) => {
        const sessionId = identity.sessionId || startSessionId;
        if (!sessionId)
            return;
        const cached = sessionRuntimeCacheRef.current.get(sessionId);
        if (!cached)
            return;
        const baseState: AppState = {
            ...currentStateRef.current,
            ...cached,
        };
        const nextState = appReducer(baseState, action);
        sessionRuntimeCacheRef.current.set(sessionId, createSessionRuntimeSnapshot(nextState));
    };
    const scopedDispatch = (action: AppAction) => {
        if (isStreamVisible()) {
            dispatch(action);
        }
        else {
            reduceHiddenRuntime(action);
        }
    };
    const updateActiveStreamHandle = (updates: Partial<{
        sessionId: string | null;
        runId: string | null;
    }>) => {
        if (!isCurrentStream())
            return;
        activeStreamRef.current = {
            token: streamToken,
            sessionId: updates.sessionId !== undefined ? updates.sessionId : activeStreamRef.current?.sessionId ?? identity.sessionId,
            runId: updates.runId !== undefined ? updates.runId : activeStreamRef.current?.runId ?? identity.runId,
            controller: activeStreamRef.current?.controller ?? ownedController,
        };
    };
    return { identity, isCurrentStream, isStreamVisible, scopedDispatch, updateActiveStreamHandle };
}
export type StreamOwnership = ReturnType<typeof createStreamOwnership>;
