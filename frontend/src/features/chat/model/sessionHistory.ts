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
        kind: step.kind,
        round: step.round ?? undefined,
        callId: step.call_id ?? undefined,
        seq: step.seq ?? undefined,
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
export function latestAssistantThinkingSteps(messages: Message[], runId?: string | null): ThinkingStep[] {
    // 恢复历史 Run 时只认该 Run 的消息。父 Run 与子 Run 的助手消息都可能有
    // thinking_steps，取全局最后一条会把别的 Run 的记录混进来。
    const scoped = runId ? messages.filter((message) => message.runId === runId) : messages;
    const latestWithSteps = [...scoped]
        .reverse()
        .find((m) => m.role === 'assistant' && (m.thinkingSteps?.length ?? 0) > 0);
    if (!latestWithSteps)
        return [];
    // 同一次 Run 续跑会新建 turn 但复用 assistant_message_id；历史按 turn
    // 分开投影后，同一助手消息会变成多条，各自只带本 turn 的步骤。合并同 id
    // 的步骤，刷新后才不会丢掉续跑前的阶段记录。
    const sameMessage = scoped.filter(
        (m) => m.role === 'assistant' && m.id === latestWithSteps.id,
    );
    if (sameMessage.length <= 1)
        return latestWithSteps.thinkingSteps || [];
    return sameMessage.flatMap((m) => m.thinkingSteps || []);
}
