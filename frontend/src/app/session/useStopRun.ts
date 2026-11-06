import { controlTripRun } from "../../features/travel/api/runs";
import { useCallback } from "react";
import { useApp } from "../state/AppContext";
import { stopOutcomeFromError } from "../../features/travel/model/stopOutcome";
import { isTripRunStatus } from "../../features/travel/types/runs";
import { stopRunUiState } from "./stopRunUi";
import { abortSessionStream } from "./streamRegistry";
export function useStopRun() {
    const { state, dispatch, activeStreamsRef, currentStateRef } = useApp();
    const stopRun = useCallback(async () => {
        const runId = state.currentTripRunId;
        const sessionId = state.currentSessionId;
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
        if (currentStateRef.current.currentTripRunId !== runId || currentStateRef.current.currentSessionId !== sessionId) {
            return;
        }
        abortSessionStream(activeStreamsRef.current, currentStateRef.current);
        dispatch({ type: 'SET_STREAMING', payload: false });
        if (cancelAccepted && hadPendingDecision) {
            dispatch({ type: 'MARK_PENDING_DECISIONS_CANCELLED' });
        }
        const uiState = stopRunUiState({ hasRun: Boolean(runId), accepted: cancelAccepted, hadPendingDecision });
        dispatch({ type: 'SET_INPUT_MODE', payload: uiState.inputMode });
        const msgs = state.currentMessages;
        const lastMsg = msgs[msgs.length - 1];
        if (lastMsg?.role === 'assistant' && !hadPendingDecision) {
            dispatch({
                type: 'UPDATE_MESSAGE_BY_ID',
                payload: uiState.markLastInterrupted
                    ? { id: lastMsg.id, type: 'interrupted', streamCompleted: true }
                    : {
                        id: lastMsg.id,
                        type: 'error',
                        content: cancelMessage || '这个页面已经停止接收结果，但规划可能仍在继续。稍后回到这趟旅行看它的状态。',
                        displayContent: cancelMessage || '这个页面已经停止接收结果，但规划可能仍在继续。稍后回到这趟旅行看它的状态。',
                        streamCompleted: true,
                    },
            });
        }
    }, [
        activeStreamsRef,
        currentStateRef,
        state.currentMessages,
        state.currentTripRunId,
        state.currentTripRunStatus,
        state.currentSessionId,
        dispatch,
    ]);
    return { stopRun };
}
