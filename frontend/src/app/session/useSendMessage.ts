import { createStreamOwnership } from "./streamOwnership";
import { createStreamEvents } from "./streamEvents";
import { createStreamFrameBatch } from "../../features/chat/model/streamFrameBatch";
import { useCallback, useRef } from "react";
import { useApp } from "../state/AppContext";
import { streamChat } from "../../features/chat/api/streamChat";
import { generateId } from "../../lib/utils";
import { useSessionManager } from "./useSessionManager";
import { type Message } from "../../features/chat/types/messages";
import { type ChatRequest } from "../../features/chat/types/requests";
import { type ControlledTripIdentity, type JourneyRoute, type PlanGateDecisionAction, type RouteDecision, type UnderstandingAnswer } from "../../features/travel/types/planner";
export function useSendMessage() {
    const { state, dispatch, activeStreamAbortRef, activeStreamRef, currentStateRef, sessionRuntimeCacheRef, pendingFollowupsRef, setPendingFollowups } = useApp();
    const { refreshSessions, setLastSession } = useSessionManager();
    const sendInFlightRef = useRef(false);
    const sendMessage = useCallback(async (text: string, options?: {
        displayText?: string;
        messageId?: string;
        assistantPendingLabel?: string;
        resumeRunId?: string | null;
        route?: JourneyRoute;
        routeDecision?: RouteDecision;
        controlledTripIdentity?: ControlledTripIdentity;
        gateDecision?: {
            action: PlanGateDecisionAction;
            content?: string;
            answers?: UnderstandingAnswer[];
            approval_token?: string;
        };
        onRequestError?: (error: Error) => void;
        requireResponse?: boolean;
        newTrip?: boolean;
    }) => {
        if (!text.trim() || state.isStreaming || sendInFlightRef.current || (options?.requireResponse && activeStreamRef.current))
            return false;
        sendInFlightRef.current = true;
        const ownedController = new AbortController();
        const effectiveSignal = ownedController.signal;
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
            id: options?.messageId ?? generateId(),
            role: 'user',
            content: text,
            displayContent: options?.displayText || text,
            timestamp: new Date(),
        };
        if (!state.currentMessages.some(message => message.id === userMessage.id)) {
            dispatch({ type: 'ADD_MESSAGE', payload: userMessage });
        }
        // 从首页提交即进入工作台；此标记只在新会话（CLEAR_CHAT）时复位。
        dispatch({ type: 'ENTER_WORKSPACE' });
        if (options?.newTrip) {
            dispatch({ type: 'SET_CONTROLLED_TRIP_IDENTITY', payload: options.controlledTripIdentity ?? null });
        }
        if (startSessionId && pendingFollowupsRef.current[startSessionId]?.length) {
            setPendingFollowups(current => ({
                ...current,
                [startSessionId]: (current[startSessionId] ?? []).map(item => ({ ...item, status: 'waiting' })),
            }));
        }
        dispatch({ type: 'SET_STREAMING', payload: true });
        // 同 Run 的失败/中断续跑会复用原 assistant_message_id；保留已有步骤，
        // 刷新后后端合并回放的记录才与实时一致。已完成 Run 的补充会新建子 Run，
        // 仍必须清空，不能把父 Run 的记录并进子 Run。
        const resumingSameRun = Boolean(
          options?.resumeRunId
          && options.resumeRunId === state.currentTripRunId
          && (state.currentTripRunStatus === 'failed' || state.currentTripRunStatus === 'interrupted'),
        );
        if (!resumingSameRun)
            dispatch({ type: 'SET_THINKING_STEPS', payload: [] });
        dispatch({ type: 'CLEAR_TRACE', payload: { preservePlanGate: Boolean(options?.gateDecision) } });
        const request: ChatRequest = {
            messages: [{
                    role: userMessage.role,
                    content: userMessage.content,
                    message_id: userMessage.id,
                    type: userMessage.type || 'normal',
                }],
            session_id: state.currentSessionId,
            run_id: initialRunId,
            route: options?.route ?? null,
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
        const events = createStreamEvents(ownership, assistantMessage, text, state.currentTripRunId, options?.assistantPendingLabel, currentStateRef, setLastSession, frame, options?.gateDecision?.action, resumingSameRun);
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
                options?.onRequestError?.(error);
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
                    // 恢复失败时保留已经收到的交付结果。
                }
            }
        }
        finally {
            sendInFlightRef.current = false;
            flushFrameNow();
            if (!effectiveSignal.aborted) {
                scopedDispatch({ type: 'SET_STREAMING', payload: false });
            }
            const completedWhileVisible = isStreamVisible();
            const completedSessionId = identity.sessionId || startSessionId;
            if (activeStreamAbortRef.current === ownedController) {
                activeStreamAbortRef.current = null;
            }
            if (activeStreamRef.current?.token === streamToken) {
                activeStreamRef.current = null;
            }
            if (completedSessionId && pendingFollowupsRef.current[completedSessionId]?.length) {
                const status = events.completed && !events.awaitingInput && !requestFailed && !events.failed && !effectiveSignal.aborted
                    && completedWhileVisible
                    ? 'ready' : 'paused';
                setPendingFollowups(current => ({
                    ...current,
                    [completedSessionId]: (current[completedSessionId] ?? []).map(item => ({
                        ...item, status: item.editing ? 'paused' : status,
                    })),
                }));
            }
            try {
                await refreshSessions();
            }
            catch {
                // 会话列表刷新失败不影响本次对话结果。
            }
            if (identity.sessionId && completedWhileVisible) {
                setLastSession(identity.sessionId);
            }
        }
        return !requestFailed && !events.failed && !effectiveSignal.aborted
            && (!options?.requireResponse || events.completed || events.awaitingInput);
    }, [
        activeStreamAbortRef,
        activeStreamRef,
        currentStateRef,
        dispatch,
        refreshSessions,
        sessionRuntimeCacheRef,
        pendingFollowupsRef,
        setLastSession,
        setPendingFollowups,
        state,
    ]);
    return { sendMessage };
}
