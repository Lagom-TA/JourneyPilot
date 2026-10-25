import { createStreamOwnership } from "./streamOwnership";
import { createStreamEvents } from "./streamEvents";
import { createStreamFrameBatch } from "../../features/chat/model/streamFrameBatch";
import { useCallback } from "react";
import { useApp } from "../state/AppContext";
import { streamChat } from "../../features/chat/api/streamChat";
import { generateId } from "../../lib/utils";
import { useSessionManager } from "./useSessionManager";
import { type Message } from "../../features/chat/types/messages";
import { type ChatRequest } from "../../features/chat/types/requests";
import { type ControlledTripIdentity, type JourneyRoute, type PlanGateDecisionAction, type RouteDecision } from "../../features/travel/types/planner";
export function useSendMessage() {
    const { state, dispatch, activeStreamAbortRef, activeStreamRef, currentStateRef, sessionRuntimeCacheRef } = useApp();
    const { refreshSessions, setLastSession } = useSessionManager();
    const sendMessage = useCallback(async (text: string, signal?: AbortSignal, options?: {
        displayText?: string;
        assistantPendingLabel?: string;
        resumeRunId?: string | null;
        route?: JourneyRoute;
        routeDecision?: RouteDecision;
        controlledTripIdentity?: ControlledTripIdentity;
        gateDecision?: {
            action: PlanGateDecisionAction;
            content?: string;
        };
    }) => {
        if (!text.trim() || state.isStreaming)
            return false;
        const ownedController = signal ? null : new AbortController();
        const effectiveSignal = signal ?? ownedController!.signal;
        if (ownedController)
            activeStreamAbortRef.current = ownedController;
        const streamToken = generateId();
        const startSessionId = state.currentSessionId || null;
        const startEpoch = state.conversationEpoch;
        const initialRunId = options?.resumeRunId || null;
        activeStreamRef.current = {
            token: streamToken,
            sessionId: startSessionId,
            runId: initialRunId,
            controller: ownedController,
        };
        const userMessage: Message = {
            id: generateId(),
            role: 'user',
            content: text,
            displayContent: options?.displayText || text,
            timestamp: new Date(),
        };
        dispatch({ type: 'ADD_MESSAGE', payload: userMessage });
        if (options?.controlledTripIdentity) {
            dispatch({ type: 'SET_CONTROLLED_TRIP_IDENTITY', payload: options.controlledTripIdentity });
        }
        if (options?.gateDecision) {
            dispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
        }
        dispatch({ type: 'SET_STREAMING', payload: true });
        dispatch({ type: 'SET_THINKING_STEPS', payload: [] });
        dispatch({ type: 'CLEAR_TRACE' });
        const request: ChatRequest = {
            messages: [{
                    role: userMessage.role,
                    content: userMessage.content,
                    message_id: userMessage.id,
                    type: userMessage.type || 'normal',
                }],
            session_id: state.currentSessionId,
            run_id: initialRunId,
            route: options?.route ?? (initialRunId ? 'trip_refinement' : null),
            route_decision: options?.routeDecision ?? null,
            ...(options?.controlledTripIdentity
                ? { controlled_trip_identity: options.controlledTripIdentity }
                : {}),
            preset_id: state.activePresetId,
        };
        if (options?.gateDecision) {
            request.gate_decision = options.gateDecision;
        }
        const assistantTempId = generateId();
        const assistantMessage: Message = {
            id: assistantTempId,
            role: 'assistant',
            content: '',
            displayContent: '',
            timestamp: new Date(),
            pendingStatusText: options?.assistantPendingLabel,
        };
        dispatch({ type: 'ADD_MESSAGE', payload: assistantMessage });
        const ownership = createStreamOwnership(streamToken, startSessionId, startEpoch, initialRunId, ownedController, activeStreamRef, currentStateRef, sessionRuntimeCacheRef, dispatch);
        const { identity, scopedDispatch, isStreamVisible } = ownership;
        const frame = createStreamFrameBatch(scopedDispatch, assistantMessage);
        const { flushFrameNow } = frame;
        const events = createStreamEvents(ownership, assistantMessage, text, state.currentTripRunId, options?.assistantPendingLabel, currentStateRef, setLastSession, frame);
        const { protocol } = events;
        let requestFailed = false;
        let deliveryStreamInterrupted = false;
        try {
            await streamChat(request, events.handleEvent, (error) => {
                if (protocol.confirmedBundle && !protocol.error) {
                    deliveryStreamInterrupted = true;
                    return;
                }
                requestFailed = true;
                scopedDispatch({
                    type: 'UPDATE_LAST_MESSAGE',
                    payload: {
                        content: `请求失败: ${error.message}`,
                        displayContent: `请求失败: ${error.message}`,
                        type: 'error',
                        streamCompleted: true,
                    },
                });
            }, effectiveSignal);
            if ((deliveryStreamInterrupted || protocol.readyEvent) && !protocol.finalized && !protocol.error) {
                try {
                    await protocol.recoverDeliveryTerminal();
                }
                catch {
                }
            }
        }
        finally {
            flushFrameNow();
            if (!effectiveSignal.aborted) {
                scopedDispatch({ type: 'SET_STREAMING', payload: false });
            }
            const completedWhileVisible = isStreamVisible();
            if (ownedController && activeStreamAbortRef.current === ownedController) {
                activeStreamAbortRef.current = null;
            }
            if (activeStreamRef.current?.token === streamToken) {
                activeStreamRef.current = null;
            }
            try {
                await refreshSessions();
            }
            catch {
            }
            if (identity.sessionId && completedWhileVisible) {
                setLastSession(identity.sessionId);
            }
        }
        return !requestFailed && !effectiveSignal.aborted;
    }, [
        activeStreamAbortRef,
        activeStreamRef,
        currentStateRef,
        dispatch,
        refreshSessions,
        sessionRuntimeCacheRef,
        setLastSession,
        state,
    ]);
    return { sendMessage };
}
