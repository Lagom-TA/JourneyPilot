import { generateId } from "../../../lib/utils";
import { normalizeContextReport } from "./contextReport";
import { normalizeContextCompactionEvent } from "./contextCompaction";
import { type ChatSession, type Message, type ThinkingStep } from "../types/messages";
import { type FinalAnswerCitation, type InformationAnnotation } from "../types/citations";
import { type SessionDetail, type SessionSummary } from "../types/sessions";
import { type TripRunStatus } from "../../travel/types/runs";
import { stripAssistantControlBlocks } from "./visibleContent";
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
export function mapCitations(raw: SessionDetail['messages'][number]['citations']): FinalAnswerCitation[] {
    return (raw || []).map((citation) => ({
        citationId: citation.citation_id,
        claimText: citation.claim_text,
        sources: (citation.sources || []).map((source) => ({
            title: source.title,
            url: source.url,
            sourceName: source.source_name,
            snippet: source.snippet,
            authorityLabel: source.authority_label,
            retrievedAt: source.retrieved_at,
        })),
    })).filter((citation) => citation.citationId && citation.sources.length > 0);
}
export function mapAnnotations(raw: SessionDetail['messages'][number]['annotations']): InformationAnnotation[] {
    return (raw || []).map((annotation) => ({
        annotationId: annotation.annotation_id,
        kind: annotation.kind,
        label: annotation.label,
        detail: annotation.detail,
    })).filter((annotation) => annotation.annotationId && annotation.label);
}
export function mapMessage(raw: SessionDetail['messages'][number]): Message {
    const persistedContent = raw.content || '';
    const persistedDisplayContent = raw.display_content || persistedContent;
    const content = raw.role === 'assistant'
        ? stripAssistantControlBlocks(persistedContent)
        : persistedContent;
    const displayContent = raw.role === 'assistant'
        ? stripAssistantControlBlocks(persistedDisplayContent)
        : persistedDisplayContent;
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
        citations: mapCitations(raw.citations),
        annotations: mapAnnotations(raw.annotations),
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
