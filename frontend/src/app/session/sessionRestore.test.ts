import { describe, expect, it } from 'vitest';
import { appReducer } from '../state/appReducer';
import { initialState } from '../state/initialState';
import { createSessionRuntimeSnapshot } from './runtimeSnapshot';
import { planRequestedRun, sessionLoadFailureMessage } from './sessionRestore';
import { type TripRunDetailResponse, type TripRunResponse } from '../../features/travel/types/runs';

const run = (runId: string, sessionId = 'A'): TripRunResponse => ({
    run_id: runId,
    session_id: sessionId,
    mode: 'deep',
    status: 'completed',
    title: null,
    request_message_id: 'request-1',
    assistant_message_id: 'assistant-1',
    parent_run_id: null,
    current_node: null,
    resume_policy: 'resume',
    last_error_code: null,
    attempt: 1,
    created_at: '2026-10-25T08:00:00Z',
    updated_at: '2026-10-25T08:00:00Z',
    started_at: null,
    completed_at: null,
    cancelled_at: null,
});

const detail = (runId: string, sessionId = 'A'): TripRunDetailResponse => ({
    run: run(runId, sessionId),
    controlled_trip_identity: null,
    state: {
        run_id: runId,
        status: 'completed',
        current_node: null,
        completed_nodes: [],
        latest_state_summary: {},
        pending_user_choice: null,
        trace_event_count: 0,
        pending_monitor_trigger_count: 0,
        last_error: null,
        updated_at: '2026-10-25T08:00:00Z',
    },
    execution: null,
    available_actions: [],
    events: [],
});

const errorState = { sessionId: 'A', runId: 'run-old', message: '无法打开' };

describe('planRequestedRun', () => {
    it('requests the latest run without an error', () => {
        expect(planRequestedRun({
            sessionId: 'A', requestedRunId: 'run-latest', latestRun: run('run-latest'),
            requestedRunDetail: null, requestedRunDetailFailed: false,
        })).toEqual({ selectedRun: run('run-latest'), readOnly: false, failure: null });
    });

    it('surfaces a requested historical run that could not be loaded instead of falling back', () => {
        const plan = planRequestedRun({
            sessionId: 'A', requestedRunId: 'run-old', latestRun: run('run-latest'),
            requestedRunDetail: null, requestedRunDetailFailed: true,
        });
        expect(plan.selectedRun).toBeNull();
        expect(plan.readOnly).toBe(true);
        expect(plan.failure).toBe('run_detail_unavailable');
    });

    it('rejects a requested run that belongs to another session', () => {
        const plan = planRequestedRun({
            sessionId: 'A', requestedRunId: 'run-old', latestRun: run('run-latest'),
            requestedRunDetail: detail('run-old', 'B'), requestedRunDetailFailed: false,
        });
        expect(plan.failure).toBe('run_session_mismatch');
        expect(plan.selectedRun).toBeNull();
    });

    it('selects a loaded historical run read-only and leaves no failure', () => {
        const plan = planRequestedRun({
            sessionId: 'A', requestedRunId: 'run-old', latestRun: run('run-latest'),
            requestedRunDetail: detail('run-old'), requestedRunDetailFailed: false,
        });
        expect(plan.selectedRun?.run_id).toBe('run-old');
        expect(plan.readOnly).toBe(true);
        expect(plan.failure).toBeNull();
    });
});

describe('sessionLoadFailureMessage', () => {
    it('describes both failure kinds', () => {
        expect(sessionLoadFailureMessage('run_detail_unavailable')).toContain('生成记录');
        expect(sessionLoadFailureMessage('run_session_mismatch')).toContain('不属于');
    });
});

describe('sessionLoadError reducer state', () => {
    it('sets and clears the explicit error', () => {
        const withError = appReducer(initialState, { type: 'SET_SESSION_LOAD_ERROR', payload: errorState });
        expect(withError.sessionLoadError).toEqual(errorState);
        expect(appReducer(withError, { type: 'CLEAR_SESSION_LOAD_ERROR' }).sessionLoadError).toBeNull();
    });

    it('clears the error when a session runtime is restored', () => {
        const withError = appReducer(initialState, { type: 'SET_SESSION_LOAD_ERROR', payload: errorState });
        const state = { ...withError, currentSessionId: 'A' };
        const snapshot = createSessionRuntimeSnapshot(state);
        expect(appReducer(state, { type: 'RESTORE_SESSION_RUNTIME', payload: snapshot }).sessionLoadError).toBeNull();
    });

    it('clears the error on a new trip', () => {
        const withError = appReducer(initialState, { type: 'SET_SESSION_LOAD_ERROR', payload: errorState });
        expect(appReducer(withError, { type: 'CLEAR_CHAT' }).sessionLoadError).toBeNull();
    });
});
