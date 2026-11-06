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
import { type UnderstandingQuestion } from "../../features/travel/types/planner";
import { type ChatSession } from "../../features/chat/types/messages";
import { tripRunRecoveryFromDetail, type TripRunDetailResponse } from "../../features/travel/types/runs";
import { isPublicDeliveryBundle } from "../../features/travel/types/delivery";
import { planRequestedRun, sessionLoadFailureMessage } from "./sessionRestore";
import { findSessionStream, pendingStreamCacheKey } from "./streamRegistry";
import { appReducer } from "../state/appReducer";
export function useSessionManager() {
    const { state, dispatch, activeStreamsRef, currentStateRef, sessionRuntimeCacheRef, setPendingFollowups } = useApp();
    const openSessionSeqRef = useRef(0);
    const earlierHistoryInFlightRef = useRef(false);
    const cacheCurrentRuntimeIfStreaming = useCallback((nextSessionId: string) => {
        const current = currentStateRef.current;
        const currentSessionId = current.currentSessionId;
        if (currentSessionId === nextSessionId)
            return;
        const activeStream = findSessionStream(activeStreamsRef.current, currentSessionId, current.conversationEpoch);
        if (!activeStream)
            return;
        sessionRuntimeCacheRef.current.set(currentSessionId ?? pendingStreamCacheKey(activeStream.token), createSessionRuntimeSnapshot(current));
    }, [activeStreamsRef, currentStateRef, sessionRuntimeCacheRef]);
    const refreshSessions = useCallback(async (): Promise<ChatSession[]> => {
        const rawSessions = await listSessions();
        const sessions = rawSessions.map(mapSummary);
        dispatch({ type: 'SET_SESSIONS', payload: sessions });
        return sessions;
    }, [dispatch]);
    const openSession = useCallback(async (sessionId: string, requestedRunId?: string) => {
        const seq = openSessionSeqRef.current + 1;
        openSessionSeqRef.current = seq;
        const currentBeforeOpen = currentStateRef.current;
        const activeStream = findSessionStream(activeStreamsRef.current, sessionId, currentBeforeOpen.conversationEpoch);
        const useLiveStream = Boolean(activeStream && (!requestedRunId || requestedRunId === activeStream.runId));
        if (useLiveStream && currentBeforeOpen.currentSessionId === sessionId) {
            setLastSession(sessionId);
            return;
        }
        cacheCurrentRuntimeIfStreaming(sessionId);
        const cachedRuntime = sessionRuntimeCacheRef.current.get(sessionId);
        if (useLiveStream && cachedRuntime) {
            currentStateRef.current = {
                ...currentStateRef.current,
                ...cachedRuntime,
                conversationEpoch: currentStateRef.current.conversationEpoch + 1,
            };
            dispatch({ type: 'RESTORE_SESSION_RUNTIME', payload: cachedRuntime });
            setLastSession(sessionId);
            return;
        }
        try {
        const [detail, runListResult] = await Promise.all([
            getSessionDetail(sessionId),
            listTripRuns({ sessionId, mode: 'deep', limit: 80 }).catch(() => null),
        ]);
        if (seq !== openSessionSeqRef.current)
            return;
        cacheCurrentRuntimeIfStreaming(sessionId);
        const latestRun = runListResult?.runs[0] || null;
        const requestedRunIsLatest = Boolean(requestedRunId && latestRun?.run_id === requestedRunId);
        let requestedRunDetail: TripRunDetailResponse | null = null;
        let requestedRunDetailFailed = false;
        if (requestedRunId && !requestedRunIsLatest) {
            try {
                requestedRunDetail = await getTripRunDetail(requestedRunId);
            }
            catch {
                requestedRunDetailFailed = true;
            }
        }
        if (seq !== openSessionSeqRef.current)
            return;
        const runPlan = planRequestedRun({ sessionId, requestedRunId, latestRun, requestedRunDetail, requestedRunDetailFailed });
        const selectedRun = runPlan.selectedRun;
        const currentTripRunReadOnly = runPlan.readOnly;
        const [selectedRunDetail, currentBundleResult] = selectedRun
            ? await Promise.all([
                requestedRunDetail ?? getTripRunDetail(selectedRun.run_id).catch(() => null),
                getCurrentDeliveryBundle(selectedRun.run_id, sessionId)
                    .then((bundle) => (isPublicDeliveryBundle(bundle) && bundle.manifest.run_id === selectedRun.run_id
                    ? { bundle, failed: false }
                    : { bundle: null, failed: true }))
                    .catch(() => ({ bundle: null, failed: true })),
            ])
            : [null, { bundle: null, failed: false }];
        if (seq !== openSessionSeqRef.current)
            return;
        const pendingRunChoice = selectedRunDetail?.state.pending_user_choice;
        const currentTripRunStatus = selectedRunDetail?.run.status ?? null;
        const hasCancelledChoice = pendingRunChoice?.read_only === true
            && pendingRunChoice?.terminal_status === 'cancelled';
        const messages = detail.messages.map(mapMessage);
        let restoredPlanGate = null;
        let restoredUnderstandingQuestions: {
            runId: string;
            revision: number;
            approvalToken: string;
            questions: UnderstandingQuestion[];
            retryLocation: boolean;
            retryResearch?: boolean;
            message?: string;
        } | null = null;
        if (pendingRunChoice && selectedRun && currentTripRunStatus === 'awaiting_input') {
            const choiceType = String(pendingRunChoice?.type || '');
            const payload = pendingRunChoice.payload && typeof pendingRunChoice.payload === 'object'
                ? pendingRunChoice.payload as Record<string, unknown>
                : {};
            if (choiceType === 'approval_gate' && pendingRunChoice?.gate === 'plan') {
                restoredPlanGate = normalizePlanApprovalGate({
                    run_id: selectedRun.run_id,
                    gate: 'plan',
                    payload,
                }, hasCancelledChoice ? 'cancelled' : 'pending', 'restored');
            }
            else if (choiceType === 'understanding_questions' && Array.isArray(payload.questions) && !hasCancelledChoice) {
                restoredUnderstandingQuestions = {
                    runId: selectedRun.run_id,
                    revision: typeof payload.revision === 'number' ? payload.revision : 0,
                    approvalToken: typeof payload.approval_token === 'string' ? payload.approval_token : '',
                    questions: payload.questions as UnderstandingQuestion[],
                    retryLocation: Array.isArray(payload.decision_options) && payload.decision_options.includes('retry'),
                    retryResearch: pendingRunChoice.gate === 'research',
                    message: typeof payload.message === 'string' ? payload.message : undefined,
                };
            }
        }
        const latestSummaryCard = [...detail.messages]
            .reverse()
            .map((message) => normalizeTripSummaryCard(message.trip_summary_card))
            .find((card) => card !== null) || null;
        const researchStarted = hasResearchStarted(messages);
        const restoredStepMessages = researchStarted ? projectVisibleMessages(messages) : messages;
        const restoredIdentity = selectedRunDetail?.controlled_trip_identity ?? null;
        let deliveryBundle = currentBundleResult.bundle;
        if (!deliveryBundle && selectedRun?.parent_run_id) {
            deliveryBundle = await getCurrentDeliveryBundle(selectedRun.parent_run_id, sessionId)
                .then((bundle) => isPublicDeliveryBundle(bundle) && bundle.manifest.run_id === selectedRun.parent_run_id ? bundle : null)
                .catch(() => null);
            if (seq !== openSessionSeqRef.current) return;
        }
        const deliveryBundleLoadState: SessionRuntimeSnapshot['deliveryBundleLoadState'] = deliveryBundle
            ? { status: 'ready', message: null }
            : currentTripRunStatus === 'completed' && currentBundleResult.failed
                ? { status: 'error', message: '暂时无法加载这趟旅行的正式结果，请稍后重试。' }
                : { status: 'idle', message: null };
        const restoredRuntime: SessionRuntimeSnapshot = {
            conversationEpoch: currentStateRef.current.conversationEpoch,
            currentSessionId: sessionId,
            currentTripRunId: selectedRun?.run_id ?? null,
            currentTripRunStatus,
            currentTripRunRecovery: tripRunRecoveryFromDetail(selectedRunDetail),
            currentTripRunReadOnly,
            tripRunSource: selectedRun ? 'live' : 'none',
            tripRunRefreshKey: currentStateRef.current.tripRunRefreshKey,
            currentMessages: projectMessagesForRunLifecycle(messages, currentTripRunStatus),
            historyPaging: {
                nextBefore: detail.next_before,
                hasMore: detail.has_more,
                loading: false,
            },
            thinkingSteps: latestAssistantThinkingSteps(restoredStepMessages, selectedRun?.run_id ?? null),
            deliveryBundle,
            deliveryBundleLoadState,
            tripSummaryCard: latestSummaryCard,
            planApprovalGate: restoredPlanGate,
            understandingQuestions: restoredUnderstandingQuestions,
            workspaceActive: Boolean(selectedRun) || messages.length > 0,
            pendingRouteConfirmation: null,
            lastRouteDecision: null,
            controlledTripIdentity: restoredIdentity,
            runCostLive: null,
            runCostSummary: null,
            isStreaming: false,
            isSynthesizing: false,
            canvasOpen: deliveryBundle !== null,
            mobileCanvasOpen: false,
            inputMode: 'normal',
        };
        cacheCurrentRuntimeIfStreaming(sessionId);
        const restoreAction = { type: 'RESTORE_SESSION_RUNTIME' as const, payload: restoredRuntime };
        currentStateRef.current = appReducer(currentStateRef.current, restoreAction);
        dispatch(restoreAction);
        if (runPlan.failure) {
            dispatch({
                type: 'SET_SESSION_LOAD_ERROR',
                payload: { sessionId, runId: requestedRunId ?? null, message: sessionLoadFailureMessage(runPlan.failure) },
            });
            const url = new URL(window.location.href);
            if (url.searchParams.get('session_id') === sessionId) {
                url.searchParams.delete('run_id');
                window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
            }
        }
        setLastSession(sessionId);
        }
        catch {
            if (seq !== openSessionSeqRef.current)
                return;
            dispatch({
                type: 'SET_SESSION_LOAD_ERROR',
                payload: {
                    sessionId,
                    runId: requestedRunId ?? null,
                    message: '暂时无法打开这趟旅行，请重试。',
                },
            });
        }
    }, [activeStreamsRef, cacheCurrentRuntimeIfStreaming, currentStateRef, dispatch, sessionRuntimeCacheRef]);
    const initializeSessions = useCallback(async () => {
        try {
            const sessions = await refreshSessions();
            if (currentStateRef.current.activeView !== 'chat') {
                return;
            }
            const params = new URLSearchParams(window.location.search);
            const deepLinkedSession = params.get('session_id');
            if (deepLinkedSession) {
                await openSession(deepLinkedSession, params.get('run_id') ?? undefined);
                return;
            }
            if (sessions.length === 0) {
                return;
            }
            const stored = getLastSession();
            const targetId = stored && sessions.some((session) => session.id === stored) ? stored : null;
            if (!targetId) {
                return;
            }
            if (currentStateRef.current.currentMessages.length || activeStreamsRef.current.size) return;
            await openSession(targetId);
        }
        catch {
            dispatch({
                type: 'SET_SESSION_LOAD_ERROR',
                payload: { sessionId: null, runId: null, message: '暂时无法读取旅行记录，请重试。' },
            });
        }
        finally {
            dispatch({ type: 'SESSION_INITIALIZED' });
        }
    }, [activeStreamsRef, currentStateRef, dispatch, openSession, refreshSessions]);
    const deleteSession = useCallback(async (sessionId: string) => {
        await deleteSessionRequest(sessionId);
        setPendingFollowups(previous => {
            const next = { ...previous };
            delete next[sessionId];
            return next;
        });
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
    }, [dispatch, openSession, refreshSessions, setPendingFollowups, state.currentSessionId]);
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
