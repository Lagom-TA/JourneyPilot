import { generateId } from "../../../lib/utils";
import { normalizeContextReport } from "./contextReport";
import { normalizeContextCompactionEvent } from "./contextCompaction";
import { thinkingStepStatusFromToolResult } from "./toolDisplay";
import { type Message, type ThinkingStep } from "../types/messages";
import { type SSEEvent } from "../types/events";
import { type UsageUpdateEvent } from "../types/cost";
import { type ChatAction } from "./state";
import { type StreamFrameBatch } from "./streamFrameBatch";
export function createStreamPresentation(scopedDispatch: (action: ChatAction) => void, assistantMessage: Message, pendingLabel: string | undefined, frame: StreamFrameBatch) {
    let pendingStatusCleared = !pendingLabel;
    let hasReceivedChunk = false;
    return {
        get hasReceivedChunk() { return hasReceivedChunk; },
        handle(event: SSEEvent): boolean {
            switch (event.type) {
                case 'thinking': {
                    if (!pendingStatusCleared) {
                        pendingStatusCleared = true;
                        scopedDispatch({ type: 'UPDATE_MESSAGE_BY_ID', payload: { id: assistantMessage.id, pendingStatusText: undefined } });
                    }
                    const now = new Date();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: now, tsMs: event.ts_ms, agentName: event.agent_name } });
                    const step: ThinkingStep = {
                        id: generateId(),
                        agentName: event.agent_name || '',
                        content: event.content || '',
                        stepName: event.step_name || '',
                        timestamp: now,
                        tsMs: event.ts_ms,
                    };
                    scopedDispatch({ type: 'ADD_THINKING_STEP', payload: step });
                    break;
                }
                case 'agent_progress': {
                    if (!pendingStatusCleared) {
                        pendingStatusCleared = true;
                        scopedDispatch({ type: 'UPDATE_MESSAGE_BY_ID', payload: { id: assistantMessage.id, pendingStatusText: undefined } });
                    }
                    const now = new Date();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: now, tsMs: event.ts_ms, agentName: event.agent_name } });
                    const progressStep: ThinkingStep = {
                        id: generateId(),
                        agentName: event.agent_name || '',
                        content: event.content || '',
                        stepName: event.step_name || '',
                        timestamp: now,
                        endTime: event.progress_status === 'running' ? undefined : now,
                        progressStatus: event.progress_status || 'completed',
                        resultPreview: event.result_preview,
                        tsMs: event.ts_ms,
                    };
                    scopedDispatch({ type: 'ADD_THINKING_STEP', payload: progressStep });
                    break;
                }
                case 'tool_start': {
                    if (!pendingStatusCleared) {
                        pendingStatusCleared = true;
                        scopedDispatch({ type: 'UPDATE_MESSAGE_BY_ID', payload: { id: assistantMessage.id, pendingStatusText: undefined } });
                    }
                    const now = new Date();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: now, tsMs: event.ts_ms, agentName: event.agent_name } });
                    const toolStep: ThinkingStep = {
                        id: event.tool_call_id || generateId(),
                        agentName: event.agent_name || '',
                        content: event.args_summary || '',
                        stepName: event.tool_name ? `调用 ${event.tool_name}` : '调用工具',
                        timestamp: now,
                        tsMs: event.ts_ms,
                        isToolCall: true,
                        toolName: event.tool_name,
                        toolCallId: event.tool_call_id,
                        toolStatus: 'running',
                        toolArgs: event.args_summary,
                        toolCategory: (event.category as ThinkingStep['toolCategory']) || 'other',
                        fromCache: event.from_cache || false,
                    };
                    scopedDispatch({ type: 'ADD_THINKING_STEP', payload: toolStep });
                    break;
                }
                case 'tool_result': {
                    const toolStatus = thinkingStepStatusFromToolResult(event.status);
                    const isDegraded = toolStatus === 'degraded';
                    scopedDispatch({
                        type: 'UPDATE_LAST_TOOL_STEP',
                        payload: {
                            toolCallId: event.tool_call_id,
                            agentName: event.agent_name,
                            toolName: event.tool_name,
                            toolResult: event.summary,
                            resultPreview: event.result_preview,
                            toolStatus,
                            toolCategory: (event.category as ThinkingStep['toolCategory']) || 'other',
                            fromCache: event.from_cache || false,
                            serverDurationMs: event.duration_ms,
                            toolDegraded: isDegraded,
                            fallbackFrom: event.fallback_from,
                            fallbackTo: event.fallback_to,
                        },
                    });
                    break;
                }
                case 'synthesis_start': {
                    scopedDispatch({ type: 'SET_SYNTHESIZING', payload: true });
                    break;
                }
                case 'context_report': {
                    const report = normalizeContextReport(event);
                    if (report) {
                        scopedDispatch({ type: 'UPDATE_LAST_MESSAGE', payload: { contextReport: report } });
                    }
                    break;
                }
                case 'context_compaction': {
                    const compaction = normalizeContextCompactionEvent(event);
                    if (!compaction)
                        break;
                    scopedDispatch({
                        type: 'INSERT_MESSAGE_BEFORE_ID',
                        payload: {
                            beforeId: assistantMessage.id,
                            message: {
                                id: compaction.id,
                                role: 'system',
                                content: '',
                                displayContent: '',
                                timestamp: new Date(compaction.occurredAt),
                                type: 'context_compaction',
                                contextCompaction: compaction,
                            },
                        },
                    });
                    break;
                }
                case 'usage_update': {
                    if (!event.run_id)
                        break;
                    const inputTokens = event.input_tokens ?? null;
                    const outputTokens = event.output_tokens ?? null;
                    const usage: UsageUpdateEvent = {
                        type: 'usage_update',
                        run_id: event.run_id,
                        message_id: event.message_id,
                        node: event.node ?? null,
                        agent: event.agent ?? null,
                        input_tokens: inputTokens,
                        output_tokens: outputTokens,
                        total_tokens: event.total_tokens ?? null,
                        cost_usd: event.cost_usd ?? null,
                        estimated: !!event.estimated,
                        usage_complete: event.usage_complete,
                        call_id: event.call_id,
                    };
                    frame.queueUsage(usage);
                    break;
                }
                case 'chat_chunk': {
                    if (!hasReceivedChunk) {
                        hasReceivedChunk = true;
                        scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
                        scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date(), tsMs: event.ts_ms } });
                    }
                    const content = event.show_content || event.content || '';
                    assistantMessage.content += content;
                    assistantMessage.displayContent += content;
                    frame.queueAssistantUpdate();
                    break;
                }
                default: return false;
            }
            return true;
        }
    };
}
