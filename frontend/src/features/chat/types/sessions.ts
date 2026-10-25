export type SessionStatus = 'active' | 'awaiting_clarify' | 'interrupted';
export interface SessionSummary {
    session_id: string;
    title: string;
    status: SessionStatus;
    mode: 'fast' | 'deep';
    last_message_preview: string;
    created_at: string;
    updated_at: string;
}
export interface SessionDetail extends SessionSummary {
    messages: Array<{
        id: string;
        role: 'user' | 'assistant' | 'system';
        content: string;
        display_content: string;
        timestamp: string;
        run_id?: string;
        type?: 'normal' | 'thinking' | 'error' | 'guard_blocked' | 'waiting_approval' | 'interrupted' | 'context_compaction';
        agent_name?: string;
        step_name?: string;
        task_type?: string;
        mode?: string;
        thinking_steps?: Array<{
            id: string;
            agent_name: string;
            content: string;
            step_name: string;
            timestamp: string;
            end_time?: string;
            is_tool_call?: boolean;
            tool_name?: string;
            tool_call_id?: string;
            tool_status?: 'running' | 'completed' | 'failed' | 'degraded' | 'capability_declared';
            tool_args?: string;
            tool_result?: string;
            result_preview?: Array<{
                title: string;
                detail?: string;
                url?: string;
            }>;
            progress_status?: 'running' | 'completed' | 'failed';
            tool_category?: string;
            from_cache?: boolean;
            duration_ms?: number | null;
        }>;
        context_report?: {
            referenced_sections?: Array<{
                key?: string;
                items?: string[];
            }>;
            compaction?: {
                triggered: boolean;
            };
        };
        context_compaction?: {
            event_id: string;
            source: 'manual' | 'automatic';
            occurred_at: string;
            messages_compressed: number;
            tokens_before: number;
            tokens_after: number;
            summary: string;
            key_constraints: string[];
        };
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
            kind: 'time_sensitive' | 'seasonal_reference' | 'safety_reference';
            label: string;
            detail: string;
        }>;
        trip_summary_card?: Record<string, unknown>;
    }>;
    next_before: string | null;
    has_more: boolean;
}
export interface SessionTurn {
    turn_id: string;
    cursor: string;
    messages: SessionDetail['messages'];
}
export interface SessionTurnPage {
    turns: SessionTurn[];
    next_before: string | null;
    has_more: boolean;
}
export interface ContextCompactionPayload {
    event_id: string;
    source: 'manual' | 'automatic';
    occurred_at: string;
    messages_compressed: number;
    tokens_before: number;
    tokens_after: number;
    summary: string;
    key_constraints: string[];
}
