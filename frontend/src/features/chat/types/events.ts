import { type ControlledTripIdentity, type RouteDecision } from "../../travel/types/planner";
import { type ResultPreview, type ToolExecutionStatus } from "./messages";
import { type DeliveryRevisionManifest, type PublicDeliveryBundle } from "../../travel/types/delivery";
import { type RunCostSummary } from "./cost";
export interface SSEEvent {
    type: 'chat_start' | 'thinking' | 'agent_progress' | 'agent_thinking' | 'tool_start' | 'tool_result' | 'work_explanation' | 'chat_chunk' | 'chat_complete' | 'delivery_ready' | 'run_terminal' | 'run_cancelled' | 'run_failed' | 'approval_gate_raised' | 'understanding_questions' | 'error' | 'usage_update' | 'context_report' | 'context_compaction' | 'trip_summary_card' | 'trip_identity_updated' | 'route_confirmation';
    message_id?: string;
    session_id?: string;
    run_id?: string;
    agent_name?: string;
    content?: string;
    show_content?: string;
    step_name?: string;
    message?: string;
    guard_blocked?: boolean;
    requires_input?: boolean;
    run_status?: string | null;
    gate?: string;
    route_decision?: RouteDecision;
    controlled_trip_identity?: ControlledTripIdentity;
    tool_name?: string;
    tool_call_id?: string;
    /** 公开工作说明：模型在工具轮中面向用户写出的可见正文。 */
    step_id?: string;
    round?: number;
    seq?: number;
    source?: string;
    args_summary?: string;
    summary?: string;
    result_preview?: ResultPreview[];
    progress_status?: 'running' | 'completed' | 'failed';
    category?: string;
    from_cache?: boolean;
    fallback_from?: string;
    fallback_to?: string;
    ts_ms?: number;
    duration_ms?: number;
    summary_card?: {
        headline: string;
        summary: string;
        facts: Array<{
            label: string;
            value: string;
            state: 'confirmed' | 'default' | 'deferred';
        }>;
        priorities: string[];
        current_focus: string;
        next_milestone: string | null;
        compact_line: string;
        requires_user_confirmation: boolean;
    };
    event_seq?: number;
    bundle_id?: string;
    manifest?: DeliveryRevisionManifest;
    bundle?: PublicDeliveryBundle;
    status?: 'completed' | ToolExecutionStatus;
    final_content?: string;
    event_id?: string;
    occurred_at?: string;
    key_constraints?: string[];
    node?: string;
    payload?: Record<string, unknown>;
    agent?: string | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
    total_tokens?: number | null;
    cost_usd?: number | null;
    estimated?: boolean;
    usage_complete?: boolean;
    call_id?: string;
    referenced_sections?: Array<{
        key?: unknown;
        items?: unknown;
    }>;
    compaction?: {
        triggered: boolean;
    };
    run_cost_summary?: RunCostSummary | null;
}
