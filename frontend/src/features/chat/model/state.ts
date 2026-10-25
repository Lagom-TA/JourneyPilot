import { type ChatSession, type Message, type ThinkingStep } from "../types/messages";
import { type RunCostLive, type RunCostSummary, type UsageUpdateEvent } from "../types/cost";
export interface ChatState {
    conversationEpoch: number;
    sessions: ChatSession[];
    currentMessages: Message[];
    historyPaging: {
        nextBefore: string | null;
        hasMore: boolean;
        loading: boolean;
    };
    thinkingSteps: ThinkingStep[];
    runCostLive: RunCostLive | null;
    runCostSummary: RunCostSummary | null;
    isStreaming: boolean;
    isSynthesizing: boolean;
    inputMode: 'normal' | 'stopped';
}
export type ChatAction = {
    type: 'SET_SESSIONS';
    payload: ChatSession[];
} | {
    type: 'REMOVE_SESSION';
    payload: string;
} | {
    type: 'RENAME_SESSION';
    payload: {
        id: string;
        title: string;
    };
} | {
    type: 'SET_HISTORY_PAGING_LOADING';
    payload: boolean;
} | {
    type: 'PREPEND_HISTORY';
    payload: {
        messages: Message[];
        nextBefore: string | null;
        hasMore: boolean;
    };
} | {
    type: 'ADD_MESSAGE';
    payload: Message;
} | {
    type: 'INSERT_MESSAGE_BEFORE_ID';
    payload: {
        message: Message;
        beforeId: string;
    };
} | {
    type: 'UPDATE_LAST_MESSAGE';
    payload: Partial<Message>;
} | {
    type: 'RESOLVE_WAITING_MESSAGES';
} | {
    type: 'UPDATE_MESSAGE_BY_ID';
    payload: {
        id: string;
    } & Partial<Message>;
} | {
    type: 'REMAP_MESSAGE_ID';
    payload: {
        fromId: string;
        toId: string;
    };
} | {
    type: 'SET_THINKING_STEPS';
    payload: ThinkingStep[];
} | {
    type: 'ADD_THINKING_STEP';
    payload: ThinkingStep;
} | {
    type: 'FINISH_LAST_THINKING_STEP';
    payload: {
        endTime: Date;
        tsMs?: number;
        agentName?: string;
    };
} | {
    type: 'UPDATE_LAST_TOOL_STEP';
    payload: {
        toolCallId?: string;
        agentName?: string;
        toolName?: string;
        toolResult?: string;
        resultPreview?: ThinkingStep['resultPreview'];
        toolStatus?: ThinkingStep['toolStatus'];
        toolCategory?: ThinkingStep['toolCategory'];
        fromCache?: boolean;
        serverDurationMs?: number;
        toolDegraded?: boolean;
        fallbackFrom?: string;
        fallbackTo?: string;
    };
} | {
    type: 'USAGE_UPDATE';
    payload: UsageUpdateEvent;
} | {
    type: 'SET_RUN_COST_SUMMARY';
    payload: RunCostSummary | null;
} | {
    type: 'SET_STREAMING';
    payload: boolean;
} | {
    type: 'SET_INPUT_MODE';
    payload: 'normal' | 'stopped';
} | {
    type: 'REMOVE_MESSAGE_BY_ID';
    payload: string;
} | {
    type: 'SET_SYNTHESIZING';
    payload: boolean;
};
