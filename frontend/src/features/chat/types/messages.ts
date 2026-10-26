import { type ContextReport, type ContextCompactionEvent } from "./context";
import { type SessionStatus } from "./sessions";
export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    displayContent: string;
    timestamp: Date;
    type?: 'normal' | 'thinking' | 'error' | 'guard_blocked' | 'waiting_approval' | 'interrupted' | 'context_compaction';
    agentType?: string;
    runId?: string;
    duration?: number;
    inputTokens?: number | null;
    outputTokens?: number | null;
    totalTokens?: number | null;
    reasoningTokens?: number | null;
    cachedTokens?: number | null;
    hasUsage?: boolean;
    thinkingSteps?: ThinkingStep[];
    contextReport?: ContextReport;
    contextCompaction?: ContextCompactionEvent;
    isEarlierHistory?: boolean;
    pendingStatusText?: string;
    streamCompleted?: boolean;
}
export type ToolCategory = 'internal' | 'search' | 'data' | 'calculation' | 'other';
export type ToolExecutionStatus = 'success' | 'failed' | 'degraded' | 'blocked' | 'not_applicable' | 'reference_only';
export interface ResultPreview {
    title: string;
    detail?: string;
    url?: string;
}
export interface ThinkingStep {
    progressStatus?: 'running' | 'completed' | 'failed';
    resultPreview?: ResultPreview[];
    id: string;
    agentName: string;
    content: string;
    stepName: string;
    timestamp: Date;
    endTime?: Date;
    tsMs?: number;
    serverDurationMs?: number;
    isToolCall?: boolean;
    toolName?: string;
    toolCallId?: string;
    toolStatus?: 'running' | 'completed' | 'failed' | 'degraded' | 'capability_declared';
    toolArgs?: string;
    toolResult?: string;
    toolCategory?: ToolCategory;
    fromCache?: boolean;
    toolDegraded?: boolean;
    fallbackFrom?: string;
    fallbackTo?: string;
}
export interface ChatSession {
    id: string;
    title: string;
    status: SessionStatus;
    lastMessagePreview: string;
    createdAt: Date;
    updatedAt: Date;
}
