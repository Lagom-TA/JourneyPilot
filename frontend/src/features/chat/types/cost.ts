export interface UsageUpdateEvent {
    type: 'usage_update';
    message_id?: string;
    run_id: string;
    node: string | null;
    agent: string | null;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    cost_usd: number | null;
    estimated: boolean;
    usage_complete?: boolean;
    call_id?: string;
}
export interface CostGroupBreakdown {
    agent?: string;
    node?: string;
    call_count: number;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    cost_usd: number | null;
    latency_ms: number;
}
export interface CostBottleneck {
    node: string;
    cost_usd: number | null;
    latency_ms: number;
    call_count: number;
}
export interface ToolContextSaving {
    mode: 'full' | 'deferred' | 'mixed';
    measurement_scope?: 'initial_assembly';
    estimated?: boolean;
    worker_assemblies: number;
    deferred_assemblies: number;
    schema_tokens_injected: number;
    schema_tokens_full_baseline: number;
    schema_tokens_saved: number;
    tool_context_saving: number;
    tools_exposed_initial: number;
    tools_full_baseline: number;
}
export interface RunCostSummary {
    pending_call_count?: number;
    spool_write_failed?: number;
    capture_complete?: boolean;
    run_id: string;
    call_count: number;
    priced_call_count: number;
    unpriced_call_count: number;
    estimated_call_count: number;
    error_call_count: number;
    estimated_ratio: number;
    cost_coverage_ratio: number;
    total_input_tokens: number | null;
    total_output_tokens: number | null;
    total_cached_input_tokens: number | null;
    total_reasoning_output_tokens: number | null;
    total_tokens: number | null;
    total_cache_write_input_tokens?: number | null;
    total_request_input_tokens_estimate?: number | null;
    total_tool_schema_tokens_estimate?: number | null;
    token_usage_complete?: boolean;
    cache_read_usage_complete?: boolean;
    cache_write_usage_complete?: boolean;
    reasoning_usage_complete?: boolean;
    cache_hit_ratio?: number | null;
    cost_complete?: boolean;
    partial_usage_call_count?: number;
    missing_usage_call_count?: number;
    logical_call_count?: number;
    total_cost_usd: number | null;
    currency: string;
    total_latency_ms: number;
    wall_ms: number | null;
    by_agent: CostGroupBreakdown[];
    by_node: CostGroupBreakdown[];
    bottleneck_by_cost: CostBottleneck[];
    bottleneck_by_latency: CostBottleneck[];
    tool_context_saving: ToolContextSaving | null;
    record_failed?: number;
}
export interface RunCostLive {
    runId: string;
    callCount: number;
    totalInputTokens: number;
    totalOutputTokens: number;
    totalTokens: number;
    totalCostUsd: number;
    costKnown: boolean;
    estimatedCount: number;
    incompleteCount?: number;
    seenCallIds?: string[];
    hasInputUsage?: boolean;
    hasOutputUsage?: boolean;
    hasTotalUsage?: boolean;
    lastNode: string | null;
    lastAgent: string | null;
}
