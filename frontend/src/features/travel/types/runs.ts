import { type JsonObject } from "../../../lib/json";
import { type ControlledTripIdentity } from "./planner";
export type TripRunStatus = 'created' | 'running' | 'awaiting_input' | 'completed' | 'failed' | 'interrupted' | 'cancel_requested' | 'cancelled';
export function isTripRunStatus(value: unknown): value is TripRunStatus {
    return typeof value === 'string' && [
        'created',
        'running',
        'awaiting_input',
        'completed',
        'failed',
        'interrupted',
        'cancel_requested',
        'cancelled',
    ].includes(value);
}
export function isTripRunActive(status: TripRunStatus | null): boolean {
    return status === 'created' || status === 'running';
}
export function isTripRunAwaitingInput(status: TripRunStatus | null): boolean {
    return status === 'awaiting_input';
}
export function isTripRunCancellable(status: TripRunStatus | null): boolean {
    return isTripRunActive(status) || isTripRunAwaitingInput(status);
}
export type TripRunRecoveryStatus = 'idle' | 'claimed' | 'running' | 'shutdown_requested' | 'resume_available' | 'non_resumable' | 'released' | 'recovery_contract_failure';
export interface TripRunExecutionResponse {
    status: TripRunRecoveryStatus;
    last_heartbeat_at: string | null;
    lease_expires_at: string | null;
    last_safe_checkpoint_id: string | null;
    recovery_reason: string | null;
}
export interface TripRunRecovery {
    status: TripRunRecoveryStatus;
    reason: string | null;
    resumable: boolean;
}
export function tripRunRecoveryFromDetail(detail: {
    execution: TripRunExecutionResponse | null;
    available_actions: string[];
} | null): TripRunRecovery | null {
    if (!detail?.execution)
        return null;
    return {
        status: detail.execution.status,
        reason: detail.execution.recovery_reason,
        resumable: detail.available_actions.includes('resume'),
    };
}
export interface TripRunControlRequest {
    action: 'cancel';
    session_id?: string | null;
}
export type TripRunCommandStatus = 'pending' | 'claimed' | 'consumed' | 'rejected';
export interface TripRunControlResponse {
    run_id: string;
    action: string;
    command_id: string;
    accepted: boolean;
    status: TripRunCommandStatus;
    run_status: TripRunStatus;
    message: string;
}
export interface TripRunResponse {
    run_id: string;
    session_id: string;
    mode: string;
    status: TripRunStatus;
    title: string | null;
    request_message_id: string;
    assistant_message_id: string;
    parent_run_id: string | null;
    current_node: string | null;
    resume_policy: string;
    last_error_code: string | null;
    last_error_message: string | null;
    attempt: number;
    created_at: string;
    updated_at: string;
    started_at: string | null;
    completed_at: string | null;
    cancelled_at: string | null;
}
export interface TripRunStateResponse {
    run_id: string;
    status: string;
    current_node: string | null;
    completed_nodes: string[];
    latest_state_summary: JsonObject;
    pending_user_choice: JsonObject | null;
    trace_event_count: number;
    pending_monitor_trigger_count: number;
    last_error: JsonObject | null;
    updated_at: string;
}
export interface TripRunEventResponse {
    event_id: number | null;
    run_id: string;
    sequence: number;
    event_type: string;
    payload: JsonObject;
    created_at: string;
}
export interface TripRunEventWindowResponse {
    run_id: string;
    requested_after_sequence: number;
    replay_floor_sequence: number;
    latest_sequence: number;
    next_after_sequence: number;
    window_expired: boolean;
    run_status: string;
    current_bundle_id: string | null;
    events: TripRunEventResponse[];
}
export interface TripRunDetailResponse {
    run: TripRunResponse;
    controlled_trip_identity: ControlledTripIdentity | null;
    state: TripRunStateResponse;
    execution: TripRunExecutionResponse | null;
    available_actions: string[];
    events: TripRunEventResponse[];
}
export interface TripRunListResponse {
    runs: TripRunResponse[];
    total: number;
}
