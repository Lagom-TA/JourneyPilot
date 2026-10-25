import { controlTripRun } from "../../features/travel/api/runs";
import { useCallback } from "react";
import { useApp } from "../state/AppContext";
import { stopOutcomeFromError } from "../../features/travel/model/stopOutcome";
import { isTripRunStatus } from "../../features/travel/types/runs";
export function useStopRun() {
    const { state, dispatch, activeStreamAbortRef } = useApp();
    const stopRun = useCallback(async () => {
        const runId = state.currentTripRunId;
        const hadPendingDecision = state.currentTripRunStatus === 'awaiting_input';
        let cancelAccepted = !runId;
        let cancelMessage = '';
        if (runId) {
            try {
                const result = await controlTripRun(runId, {
                    action: 'cancel',
                    session_id: state.currentSessionId,
                });
                cancelAccepted = result.accepted;
                cancelMessage = result.message || '';
                if (result.accepted && isTripRunStatus(result.run_status)) {
                    dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: result.run_status });
                }
            }
            catch (err) {
                const outcome = stopOutcomeFromError(err);
                cancelAccepted = outcome.stopped;
                cancelMessage = outcome.message ?? '';
                if (outcome.status) {
                    dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: outcome.status });
                }
            }
        }
        if (activeStreamAbortRef.current) {
            activeStreamAbortRef.current.abort();
            activeStreamAbortRef.current = null;
        }
        dispatch({ type: 'SET_STREAMING', payload: false });
        if (cancelAccepted && hadPendingDecision) {
            dispatch({ type: 'MARK_PENDING_DECISIONS_CANCELLED' });
        }
        dispatch({ type: 'SET_INPUT_MODE', payload: cancelAccepted ? 'stopped' : 'normal' });
        const msgs = state.currentMessages;
        const lastMsg = msgs[msgs.length - 1];
        if (lastMsg?.role === 'assistant' && !hadPendingDecision) {
            dispatch({
                type: 'UPDATE_MESSAGE_BY_ID',
                payload: cancelAccepted
                    ? { id: lastMsg.id, type: 'interrupted', streamCompleted: true }
                    : {
                        id: lastMsg.id,
                        type: 'error',
                        content: cancelMessage || '已断开本地流，但后端取消未确认。',
                        displayContent: cancelMessage || '已断开本地流，但后端取消未确认。',
                        streamCompleted: true,
                    },
            });
        }
    }, [
        activeStreamAbortRef,
        state.currentMessages,
        state.currentTripRunId,
        state.currentTripRunStatus,
        state.currentSessionId,
        state.planApprovalGate,
        dispatch,
    ]);
    return { stopRun };
}
