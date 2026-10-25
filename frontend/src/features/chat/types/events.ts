import { type GuidedIntakeState, type RouteDecision } from "../../travel/types/planner";
import { type ResultPreview, type ToolExecutionStatus } from "./messages";
import { type DeliveryRevisionManifest, type PublicDeliveryBundle } from "../../travel/types/delivery";
import { type InformationAnnotationKind } from "./citations";
import { type RunCostSummary } from "./cost";
export interface SSEEvent {
    type: 'chat_start' | 'thinking' | 'agent_progress' | 'agent_thinking' | 'tool_start' | 'tool_result' | 'chat_chunk' | 'chat_complete' | 'delivery_ready' | 'run_terminal' | 'run_cancelled' | 'run_failed' | 'approval_gate_raised' | 'error' | 'usage_update' | 'context_report' | 'context_compaction' | 'trip_summary_card' | 'guided_intake' | 'route_confirmation' | 'synthesis_start';
    message_id?: string;
    session_id?: string;
    run_id?: string;
    agent_name?: string;
    content?: string;
    show_content?: string;
    step_name?: string;
    message?: string;
    guard_blocked?: boolean;
    run_status?: string;
    gate?: string;
    guided_intake?: GuidedIntakeState;
    route_decision?: RouteDecision;
    tool_name?: string;
    tool_call_id?: string;
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
    citations?: Array<{
        citation_id: string;
        claim_text?: string;
        sources: Array<{
            title?: string;
            url?: string;
            source_name?: string;
            snippet?: string;
            authority_label?: string;
            retrieved_at?: string;
        }>;
    }>;
    annotations?: Array<{
        annotation_id: string;
        kind: InformationAnnotationKind;
        label: string;
        detail: string;
    }>;
    mode?: string;
    event_id?: string;
    event_type?: string;
    occurred_at?: string;
    key_constraints?: string[];
    node?: string;
    timestamp?: string;
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
