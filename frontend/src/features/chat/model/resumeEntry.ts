import { type TripRunRecovery, type TripRunStatus } from '../../travel/types/runs';

export interface ResumeEntryInput {
    isUser: boolean;
    isAlertCard: boolean;
    isGenerating: boolean;
    messageId: string;
    messageRunId?: string | null;
    /** 当前 Run 的最后一条助手消息；调整对话里它后面可能还有没有 Run 归属的提示消息。 */
    lastRunMessageId?: string;
    currentRunId: string | null;
    runStatus: TripRunStatus | null;
    recovery: TripRunRecovery | null;
    readOnly: boolean;
}

/**
 * 已交付行程的调整被中断时，生成面板不再挂载；接口说这次 Run 可恢复时，
 * 在它的最后一条助手消息下给出“继续生成”。不看消息类型：进程被杀、服务重启时
 * 没有终止事件，存下来的就是普通消息。
 */
export function showsResumeEntry(input: ResumeEntryInput): boolean {
    return !input.isUser
        && !input.isAlertCard
        && !input.isGenerating
        && Boolean(input.messageRunId)
        && input.messageRunId === input.currentRunId
        && input.lastRunMessageId === input.messageId
        && input.runStatus === 'interrupted'
        && input.recovery?.resumable === true
        && !input.readOnly;
}
