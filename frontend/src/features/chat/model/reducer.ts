import { type ChatState, type ChatAction } from "./state";
import { type RunCostLive } from "../../chat/types/cost";
export function chatReducer<T extends ChatState>(state: T, action: ChatAction): T {
    switch (action.type) {
        case 'SET_SESSIONS':
            return { ...state, sessions: action.payload };
        case 'REMOVE_SESSION':
            return {
                ...state,
                sessions: state.sessions.filter((s) => s.id !== action.payload),
            };
        case 'RENAME_SESSION':
            return {
                ...state,
                sessions: state.sessions.map((s) => s.id === action.payload.id ? { ...s, title: action.payload.title } : s),
            };
        case 'SET_HISTORY_PAGING_LOADING':
            return { ...state, historyPaging: { ...state.historyPaging, loading: action.payload } };
        case 'PREPEND_HISTORY':
            return {
                ...state,
                currentMessages: [...action.payload.messages, ...state.currentMessages],
                historyPaging: {
                    nextBefore: action.payload.nextBefore,
                    hasMore: action.payload.hasMore,
                    loading: false,
                },
            };
        case 'ADD_MESSAGE':
            return {
                ...state,
                currentMessages: [...state.currentMessages, action.payload],
            };
        case 'INSERT_MESSAGE_BEFORE_ID': {
            if (state.currentMessages.some((message) => message.id === action.payload.message.id))
                return state;
            const targetIndex = state.currentMessages.findIndex((message) => message.id === action.payload.beforeId);
            if (targetIndex < 0) {
                return { ...state, currentMessages: [...state.currentMessages, action.payload.message] };
            }
            return {
                ...state,
                currentMessages: [
                    ...state.currentMessages.slice(0, targetIndex),
                    action.payload.message,
                    ...state.currentMessages.slice(targetIndex),
                ],
            };
        }
        case 'UPDATE_LAST_MESSAGE': {
            const msgs = [...state.currentMessages];
            if (msgs.length > 0) {
                msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...action.payload };
            }
            return { ...state, currentMessages: msgs };
        }
        case 'RESOLVE_WAITING_MESSAGES': {
            let touched = false;
            const msgs = state.currentMessages.map((m) => {
                if (m.type === 'waiting_approval') {
                    touched = true;
                    return { ...m, type: 'normal' as const };
                }
                return m;
            });
            return touched ? { ...state, currentMessages: msgs } : state;
        }
        case 'UPDATE_MESSAGE_BY_ID': {
            const { id, ...updates } = action.payload;
            return {
                ...state,
                currentMessages: state.currentMessages.map((m) => m.id === id ? { ...m, ...updates } : m),
            };
        }
        case 'REMAP_MESSAGE_ID':
            return {
                ...state,
                currentMessages: state.currentMessages.map((m) => m.id === action.payload.fromId ? { ...m, id: action.payload.toId } : m),
            };
        case 'SET_THINKING_STEPS':
            return { ...state, thinkingSteps: action.payload };
        case 'ADD_THINKING_STEP': {
            const newSteps = [...state.thinkingSteps, action.payload];
            const msgs = [...state.currentMessages];
            if (msgs.length > 0) {
                const lastMsg = msgs[msgs.length - 1];
                if (lastMsg.role === 'assistant') {
                    msgs[msgs.length - 1] = { ...lastMsg, thinkingSteps: newSteps };
                }
            }
            return {
                ...state,
                thinkingSteps: newSteps,
                currentMessages: msgs,
            };
        }
        case 'FINISH_LAST_THINKING_STEP': {
            if (state.thinkingSteps.length === 0)
                return state;
            const newSteps = [...state.thinkingSteps];
            let lastIdx = newSteps.length - 1;
            if (action.payload.agentName) {
                while (lastIdx >= 0 && (newSteps[lastIdx].agentName !== action.payload.agentName || newSteps[lastIdx].isToolCall))
                    lastIdx -= 1;
            }
            if (lastIdx < 0 || newSteps[lastIdx].isToolCall || newSteps[lastIdx].progressStatus === 'running')
                return state;
            const last = newSteps[lastIdx];
            const { endTime, tsMs: nextTsMs } = action.payload;
            const serverDurationMs = !last.isToolCall && last.serverDurationMs == null && nextTsMs != null && last.tsMs != null && nextTsMs >= last.tsMs
                ? nextTsMs - last.tsMs
                : last.serverDurationMs;
            newSteps[lastIdx] = { ...last, endTime: last.endTime ?? endTime, serverDurationMs };
            const msgs = [...state.currentMessages];
            if (msgs.length > 0) {
                const lastMsg = msgs[msgs.length - 1];
                if (lastMsg.role === 'assistant' && lastMsg.thinkingSteps) {
                    msgs[msgs.length - 1] = { ...lastMsg, thinkingSteps: newSteps };
                }
            }
            return {
                ...state,
                thinkingSteps: newSteps,
                currentMessages: msgs,
            };
        }
        case 'UPDATE_LAST_TOOL_STEP': {
            if (state.thinkingSteps.length === 0)
                return state;
            const newSteps = [...state.thinkingSteps];
            const lastIdx = (() => {
                if (action.payload.toolCallId) {
                    const byId = newSteps.findIndex((step) => step.toolCallId === action.payload.toolCallId || step.id === action.payload.toolCallId);
                    return byId;
                }
                for (let i = newSteps.length - 1; i >= 0; i -= 1) {
                    const step = newSteps[i];
                    if (step.isToolCall &&
                        step.toolStatus === 'running' &&
                        (!action.payload.agentName || step.agentName === action.payload.agentName) &&
                        (!action.payload.toolName || step.toolName === action.payload.toolName)) {
                        return i;
                    }
                }
                return -1;
            })();
            if (lastIdx < 0)
                return state;
            const lastStep = newSteps[lastIdx];
            if (lastStep.isToolCall) {
                newSteps[lastIdx] = {
                    ...lastStep,
                    endTime: new Date(),
                    ...(action.payload.toolCallId !== undefined && { toolCallId: action.payload.toolCallId }),
                    toolStatus: action.payload.toolStatus ?? 'completed',
                    toolResult: action.payload.toolResult,
                    resultPreview: action.payload.resultPreview,
                    ...(action.payload.toolCategory !== undefined && { toolCategory: action.payload.toolCategory }),
                    ...(action.payload.fromCache !== undefined && { fromCache: action.payload.fromCache }),
                    ...(action.payload.serverDurationMs != null && { serverDurationMs: action.payload.serverDurationMs }),
                    ...(action.payload.toolDegraded !== undefined && { toolDegraded: action.payload.toolDegraded }),
                    ...(action.payload.fallbackFrom !== undefined && { fallbackFrom: action.payload.fallbackFrom }),
                    ...(action.payload.fallbackTo !== undefined && { fallbackTo: action.payload.fallbackTo }),
                };
                const msgs = [...state.currentMessages];
                if (msgs.length > 0) {
                    const lastMsg = msgs[msgs.length - 1];
                    if (lastMsg.role === 'assistant' && lastMsg.thinkingSteps) {
                        msgs[msgs.length - 1] = { ...lastMsg, thinkingSteps: newSteps };
                    }
                }
                return { ...state, thinkingSteps: newSteps, currentMessages: msgs };
            }
            return state;
        }
        case 'USAGE_UPDATE': {
            const ev = action.payload;
            const prev = state.runCostLive && state.runCostLive.runId === ev.run_id ? state.runCostLive : null;
            if (ev.call_id && prev?.seenCallIds?.includes(ev.call_id))
                return state;
            const inputTokens = ev.input_tokens || 0;
            const outputTokens = ev.output_tokens || 0;
            const next: RunCostLive = {
                runId: ev.run_id,
                callCount: (prev?.callCount ?? 0) + 1,
                totalInputTokens: (prev?.totalInputTokens ?? 0) + inputTokens,
                totalOutputTokens: (prev?.totalOutputTokens ?? 0) + outputTokens,
                totalTokens: (prev?.totalTokens ?? 0) + (ev.total_tokens ?? inputTokens + outputTokens),
                totalCostUsd: (prev?.totalCostUsd ?? 0) + (ev.cost_usd ?? 0),
                costKnown: (prev?.costKnown ?? false) || ev.cost_usd != null,
                estimatedCount: (prev?.estimatedCount ?? 0) + (ev.estimated ? 1 : 0),
                incompleteCount: (prev?.incompleteCount ?? 0) + (ev.usage_complete === false || ev.cost_usd == null ? 1 : 0),
                seenCallIds: ev.call_id ? [...(prev?.seenCallIds ?? []), ev.call_id] : prev?.seenCallIds,
                hasInputUsage: (prev?.hasInputUsage ?? false) || ev.input_tokens != null,
                hasOutputUsage: (prev?.hasOutputUsage ?? false) || ev.output_tokens != null,
                hasTotalUsage: (prev?.hasTotalUsage ?? false) || ev.total_tokens != null,
                lastNode: ev.node ?? prev?.lastNode ?? null,
                lastAgent: ev.agent ?? prev?.lastAgent ?? null,
            };
            return { ...state, runCostLive: next };
        }
        case 'SET_RUN_COST_SUMMARY': {
            return { ...state, runCostSummary: action.payload };
        }
        case 'SET_STREAMING':
            return { ...state, isStreaming: action.payload, isSynthesizing: action.payload ? state.isSynthesizing : false };
        case 'SET_SYNTHESIZING':
            return { ...state, isSynthesizing: action.payload };
        case 'SET_INPUT_MODE':
            return { ...state, inputMode: action.payload };
        case 'REMOVE_MESSAGE_BY_ID':
            return {
                ...state,
                currentMessages: state.currentMessages.filter((m) => m.id !== action.payload),
            };
        default: return state;
    }
}
