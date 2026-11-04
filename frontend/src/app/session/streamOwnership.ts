import { type Dispatch, type MutableRefObject } from "react";
import { appReducer } from "../state/appReducer";
import { type AppAction, type AppState } from "../state/state";
import { createSessionRuntimeSnapshot, type ActiveStreamHandle, type SessionRuntimeSnapshot } from "./runtimeSnapshot";
import { pendingStreamCacheKey } from "./streamRegistry";
export function createStreamOwnership(streamToken: string, startSessionId: string | null, startEpoch: number, initialRunId: string | null, ownedController: AbortController | null, activeStreamsRef: MutableRefObject<Map<string, ActiveStreamHandle>>, currentStateRef: MutableRefObject<AppState>, sessionRuntimeCacheRef: MutableRefObject<Map<string, SessionRuntimeSnapshot>>, dispatch: Dispatch<AppAction>) {
    const identity = { sessionId: startSessionId, runId: initialRunId };
    const isCurrentStream = () => activeStreamsRef.current.has(streamToken);
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
        const cacheKey = identity.sessionId || startSessionId || pendingStreamCacheKey(streamToken);
        const cached = sessionRuntimeCacheRef.current.get(cacheKey);
        if (!cached)
            return;
        const baseState: AppState = {
            ...currentStateRef.current,
            ...cached,
        };
        const nextState = appReducer(baseState, action);
        sessionRuntimeCacheRef.current.set(cacheKey, createSessionRuntimeSnapshot(nextState));
    };
    const scopedDispatch = (action: AppAction) => {
        if (!isCurrentStream())
            return;
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
        const activeStream = activeStreamsRef.current.get(streamToken);
        if (!activeStream)
            return;
        if (updates.sessionId) {
            const pendingKey = pendingStreamCacheKey(streamToken);
            const pending = sessionRuntimeCacheRef.current.get(pendingKey);
            if (pending) {
                sessionRuntimeCacheRef.current.delete(pendingKey);
                sessionRuntimeCacheRef.current.set(updates.sessionId, pending);
            }
        }
        activeStreamsRef.current.set(streamToken, {
            ...activeStream,
            sessionId: updates.sessionId !== undefined ? updates.sessionId : activeStream.sessionId ?? identity.sessionId,
            runId: updates.runId !== undefined ? updates.runId : activeStream.runId ?? identity.runId,
            controller: activeStream.controller ?? ownedController,
        });
    };
    return { identity, isCurrentStream, isStreamVisible, scopedDispatch, updateActiveStreamHandle };
}
export type StreamOwnership = ReturnType<typeof createStreamOwnership>;
