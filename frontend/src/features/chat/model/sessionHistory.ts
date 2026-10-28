import { generateId } from "../../../lib/utils";
import { normalizeContextReport } from "./contextReport";
import { normalizeContextCompactionEvent } from "./contextCompaction";
import { type ChatSession, type Message, type ThinkingStep } from "../types/messages";
import { type SessionDetail, type SessionSummary } from "../types/sessions";
import { type TripRunStatus } from "../../travel/types/runs";
export function mapSummary(raw: SessionSummary): ChatSession {
    return {
        id: raw.session_id,
        title: raw.title,
        status: raw.status,
        lastMessagePreview: raw.last_message_preview || '',
        createdAt: new Date(raw.created_at),
        updatedAt: new Date(raw.updated_at),
    };
}
export function mapThinkingSteps(rawSteps: SessionDetail['messages'][number]['thinking_steps']): ThinkingStep[] {
    if (!rawSteps)
        return [];
    return rawSteps.map((step) => ({
        id: step.id || generateId(),
        agentName: step.agent_name || '',
        content: step.content || '',
        stepName: step.step_name || '',
        timestamp: new Date(step.timestamp),
        endTime: step.end_time ? new Date(step.end_time) : undefined,
        serverDurationMs: step.duration_ms ?? undefined,
        isToolCall: step.is_tool_call,
        toolName: step.tool_name,
        toolCallId: step.tool_call_id,
        toolStatus: step.tool_status,
        toolArgs: step.tool_args,
        toolResult: step.tool_result,
        resultPreview: step.result_preview,
        progressStatus: step.progress_status,
        toolCategory: step.tool_category as ThinkingStep['toolCategory'],
        fromCache: step.from_cache,
    }));
}
export function mapMessage(raw: SessionDetail['messages'][number]): Message {
    const content = raw.content || '';
    const displayContent = raw.display_content || content;
    return {
        id: raw.id || generateId(),
        role: raw.role,
        content,
        displayContent,
        timestamp: new Date(raw.timestamp),
        type: raw.type,
        runId: raw.run_id,
        thinkingSteps: mapThinkingSteps(raw.thinking_steps),
        contextReport: normalizeContextReport(raw.context_report) || undefined,
        contextCompaction: normalizeContextCompactionEvent(raw.context_compaction) || undefined,
    };
}
export function projectMessagesForRunLifecycle(messages: Message[], status: TripRunStatus | null): Message[] {
    if (status === 'awaiting_input')
        return messages;
    return messages.map((message) => (message.type === 'waiting_approval'
        ? { ...message, type: 'normal' as const, streamCompleted: true }
        : message));
}
export function latestAssistantThinkingSteps(messages: Message[]): ThinkingStep[] {
    const latestWithSteps = [...messages]
        .reverse()
        .find((m) => m.role === 'assistant' && (m.thinkingSteps?.length ?? 0) > 0);
    return latestWithSteps?.thinkingSteps || [];
}
