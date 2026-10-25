import { mapSummary, mapMessage, projectMessagesForRunLifecycle, latestAssistantThinkingSteps } from "../../features/chat/model/sessionHistory";
import { getLastSession, setLastSession } from "./lastSessionStorage";
import { listSessions, deleteSession as deleteSessionRequest, renameSession as renameSessionRequest, getSessionDetail, getSessionTurns } from "../../features/chat/api/sessions";
import { listTripRuns, getTripRunDetail } from "../../features/travel/api/runs";
import { getCurrentDeliveryBundle } from "../../features/travel/api/delivery";
import { useCallback, useRef } from "react";
import { createSessionRuntimeSnapshot, type SessionRuntimeSnapshot } from "./runtimeSnapshot";
import { useApp } from "../state/AppContext";
import { normalizeTripSummaryCard } from "../../features/travel/model/tripSummaryCard";
import { normalizePlanApprovalGate } from "../../features/travel/model/planApprovalGate";
import { hasResearchStarted, projectVisibleMessages } from "../../features/chat/model/conversationFlow";
import { type ChatSession } from "../../features/chat/types/messages";
import { type ControlledTripIdentity } from "../../features/travel/types/planner";
import { tripRunRecoveryFromDetail } from "../../features/travel/types/runs";
import { isPublicDeliveryBundle } from "../../features/travel/types/delivery";
export function useSessionManager() {
    const { state, dispatch, activeStreamRef, currentStateRef, sessionRuntimeCacheRef } = useApp();
    const openSessionSeqRef = useRef(0);
    const earlierHistoryInFlightRef = useRef(false);
    const cacheCurrentRuntimeIfStreaming = useCallback((nextSessionId: string) => {
        const current = currentStateRef.current;
        const activeStream = activeStreamRef.current;
        const currentSessionId = current.currentSessionId;
        if (!currentSessionId || currentSessionId === nextSessionId)
            return;
        if (activeStream?.sessionId !== currentSessionId)
            return;
        sessionRuntimeCacheRef.current.set(currentSessionId, createSessionRuntimeSnapshot(current));
    }, [activeStreamRef, currentStateRef, sessionRuntimeCacheRef]);
    const refreshSessions = useCallback(async (): Promise<ChatSession[]> => {
        const rawSessions = await listSessions();
        const sessions = rawSessions.map(mapSummary);
        dispatch({ type: 'SET_SESSIONS', payload: sessions });
        return sessions;
    }, [dispatch]);
    const openSession = useCallback(async (sessionId: string) => {
        const seq = openSessionSeqRef.current + 1;
        openSessionSeqRef.current = seq;
        const currentBeforeOpen = currentStateRef.current;
        if (currentBeforeOpen.currentSessionId === sessionId && activeStreamRef.current?.sessionId === sessionId) {
            setLastSession(sessionId);
            return;
        }
        cacheCurrentRuntimeIfStreaming(sessionId);
        const cachedRuntime = sessionRuntimeCacheRef.current.get(sessionId);
        const activeStream = activeStreamRef.current;
        if (cachedRuntime && activeStream?.sessionId === sessionId) {
            currentStateRef.current = {
                ...currentStateRef.current,
                ...cachedRuntime,
                conversationEpoch: currentStateRef.current.conversationEpoch + 1,
            };
            dispatch({ type: 'RESTORE_SESSION_RUNTIME', payload: cachedRuntime });
            setLastSession(sessionId);
            return;
        }
        const [detail, runListResult] = await Promise.all([
            getSessionDetail(sessionId),
            listTripRuns({ sessionId, mode: 'deep', limit: 1 }).catch(() => null),
        ]);
        if (seq !== openSessionSeqRef.current)
            return;
        cacheCurrentRuntimeIfStreaming(sessionId);
        const latestRun = runListResult?.runs[0] || null;
        const [latestRunDetail, currentBundleResult] = latestRun
            ? await Promise.all([
                getTripRunDetail(latestRun.run_id).catch(() => null),
                getCurrentDeliveryBundle(latestRun.run_id, sessionId)
                    .then((bundle) => (isPublicDeliveryBundle(bundle) && bundle.manifest.run_id === latestRun.run_id
                    ? { bundle, failed: false }
                    : { bundle: null, failed: true }))
                    .catch(() => ({ bundle: null, failed: true })),
            ])
            : [null, { bundle: null, failed: false }];
        if (seq !== openSessionSeqRef.current)
            return;
        const pendingRunChoice = latestRunDetail?.state.pending_user_choice;
        const currentTripRunStatus = latestRunDetail?.run.status ?? null;
        const hasCancelledChoice = pendingRunChoice?.read_only === true
            && pendingRunChoice?.terminal_status === 'cancelled';
        let messages = detail.messages.map(mapMessage);
        let restoredPlanGate = null;
        if (pendingRunChoice && latestRun && currentTripRunStatus === 'awaiting_input') {
            const choiceType = String(pendingRunChoice?.type || '');
            if (choiceType === 'approval_gate' && pendingRunChoice?.gate === 'plan') {
                const payload = pendingRunChoice.payload && typeof pendingRunChoice.payload === 'object'
                    ? pendingRunChoice.payload as Record<string, unknown>
                    : {};
                restoredPlanGate = normalizePlanApprovalGate({
                    run_id: latestRun.run_id,
                    gate: 'plan',
                    payload,
                }, hasCancelledChoice ? 'cancelled' : 'pending');
            }
        }
        const latestSummaryCard = [...detail.messages]
            .reverse()
            .map((message) => normalizeTripSummaryCard(message.trip_summary_card))
            .find((card) => card !== null) || null;
        const researchStarted = hasResearchStarted(messages);
        const restoredStepMessages = researchStarted ? projectVisibleMessages(messages) : messages;
        const restoredIdentity = latestRunDetail?.controlled_trip_identity ?? null;
        const deliveryBundle = currentBundleResult.bundle;
        const deliveryBundleLoadState: SessionRuntimeSnapshot['deliveryBundleLoadState'] = deliveryBundle
            ? { status: 'ready', message: null }
            : currentTripRunStatus === 'completed' && currentBundleResult.failed
                ? { status: 'error', message: '暂时无法加载这趟旅行的正式结果，请稍后重试。' }
                : { status: 'idle', message: null };
        const restoredRuntime: SessionRuntimeSnapshot = {
            conversationEpoch: currentStateRef.current.conversationEpoch,
            currentSessionId: sessionId,
            currentTripRunId: latestRun?.run_id ?? null,
            currentTripRunStatus,
            currentTripRunRecovery: tripRunRecoveryFromDetail(latestRunDetail),
            tripRunSource: latestRun ? 'live' : 'none',
            tripRunRefreshKey: currentStateRef.current.tripRunRefreshKey,
            currentMessages: projectMessagesForRunLifecycle(messages, currentTripRunStatus),
            historyPaging: {
                nextBefore: detail.next_before,
                hasMore: detail.has_more,
                loading: false,
            },
            thinkingSteps: latestAssistantThinkingSteps(restoredStepMessages),
            deliveryBundle,
            deliveryBundleLoadState,
            tripSummaryCard: latestSummaryCard,
            planApprovalGate: restoredPlanGate,
            pendingGuidedIntake: null,
            pendingRouteConfirmation: null,
            lastRouteDecision: null,
            controlledTripIdentity: restoredIdentity as ControlledTripIdentity | null,
            runCostLive: null,
            runCostSummary: null,
            isStreaming: false,
            isSynthesizing: false,
            canvasOpen: deliveryBundle !== null,
            canvasFullscreen: false,
            mobileCanvasOpen: false,
            inputMode: 'normal',
        };
        dispatch({ type: 'RESTORE_SESSION_RUNTIME', payload: restoredRuntime });
        setLastSession(sessionId);
    }, [activeStreamRef, cacheCurrentRuntimeIfStreaming, currentStateRef, dispatch, sessionRuntimeCacheRef, setLastSession]);
    const initializeSessions = useCallback(async () => {
        try {
            const sessions = await refreshSessions();
            if (sessions.length === 0) {
                return;
            }
            if (state.activeView !== 'chat') {
                return;
            }
            let targetId: string | null = null;
            try {
                const stored = getLastSession();
                if (stored && sessions.some((s) => s.id === stored)) {
                    targetId = stored;
                }
            }
            catch {
            }
            if (!targetId) {
                return;
            }
            await openSession(targetId);
        }
        catch {
        }
    }, [openSession, refreshSessions, state.activeView]);
    const deleteSession = useCallback(async (sessionId: string) => {
        await deleteSessionRequest(sessionId);
        dispatch({ type: 'REMOVE_SESSION', payload: sessionId });
        if (state.currentSessionId === sessionId) {
            const sessions = await refreshSessions();
            if (sessions.length > 0) {
                await openSession(sessions[0].id);
            }
            else {
                dispatch({ type: 'CLEAR_CHAT' });
                setLastSession(null);
            }
        }
    }, [dispatch, openSession, refreshSessions, setLastSession, state.currentSessionId]);
    const renameSession = useCallback(async (sessionId: string, nextTitle: string) => {
        const trimmed = nextTitle.trim();
        if (!trimmed)
            return;
        const previousTitle = state.sessions.find((s) => s.id === sessionId)?.title ?? '';
        if (trimmed === previousTitle)
            return;
        dispatch({ type: 'RENAME_SESSION', payload: { id: sessionId, title: trimmed } });
        try {
            const updated = await renameSessionRequest(sessionId, trimmed);
            dispatch({ type: 'RENAME_SESSION', payload: { id: sessionId, title: updated.title } });
        }
        catch (err) {
            dispatch({ type: 'RENAME_SESSION', payload: { id: sessionId, title: previousTitle } });
            throw err instanceof Error ? err : new Error(String(err));
        }
    }, [dispatch, state.sessions]);
    const loadEarlierHistory = useCallback(async () => {
        const { currentSessionId, historyPaging, currentTripRunStatus } = currentStateRef.current;
        if (!currentSessionId || !historyPaging.hasMore)
            return;
        if (earlierHistoryInFlightRef.current)
            return;
        const cursor = historyPaging.nextBefore;
        if (!cursor)
            return;
        earlierHistoryInFlightRef.current = true;
        dispatch({ type: 'SET_HISTORY_PAGING_LOADING', payload: true });
        try {
            const page = await getSessionTurns(currentSessionId, cursor);
            if (currentStateRef.current.currentSessionId !== currentSessionId) {
                dispatch({ type: 'SET_HISTORY_PAGING_LOADING', payload: false });
                return;
            }
            dispatch({
                type: 'PREPEND_HISTORY',
                payload: {
                    messages: projectMessagesForRunLifecycle(page.turns.flatMap((turn) => turn.messages).map(mapMessage), currentTripRunStatus).map((message) => ({ ...message, isEarlierHistory: true })),
                    nextBefore: page.next_before,
                    hasMore: page.has_more,
                },
            });
        }
        catch {
            dispatch({ type: 'SET_HISTORY_PAGING_LOADING', payload: false });
        }
        finally {
            earlierHistoryInFlightRef.current = false;
        }
    }, [currentStateRef, dispatch]);
    return {
        refreshSessions,
        openSession,
        loadEarlierHistory,
        initializeSessions,
        deleteSession,
        renameSession,
        setLastSession,
    };
}
