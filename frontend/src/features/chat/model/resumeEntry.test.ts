import { describe, expect, it } from "vitest";
import { showsResumeEntry, type ResumeEntryInput } from "./resumeEntry";

const base: ResumeEntryInput = {
    isUser: false,
    isAlertCard: false,
    isGenerating: false,
    messageId: 'm2',
    messageRunId: 'run-child',
    lastRunMessageId: 'm2',
    currentRunId: 'run-child',
    runStatus: 'interrupted',
    recovery: { status: 'resume_available', reason: null, resumable: true },
    readOnly: false,
};

describe('showsResumeEntry', () => {
    it('被中断且可恢复的 Run，在它最后一条助手消息下给出入口', () => {
        expect(showsResumeEntry(base)).toBe(true);
    });
    it('只出现在这次 Run 的最后一条助手消息上', () => {
        expect(showsResumeEntry({ ...base, messageId: 'm1' })).toBe(false);
    });
    it('属于别的 Run 的消息不出现', () => {
        expect(showsResumeEntry({ ...base, messageRunId: 'run-parent' })).toBe(false);
        expect(showsResumeEntry({ ...base, messageRunId: undefined })).toBe(false);
    });
    it('Run 没被中断、接口不允许恢复或只读历史时不出现', () => {
        expect(showsResumeEntry({ ...base, runStatus: 'failed' })).toBe(false);
        expect(showsResumeEntry({ ...base, runStatus: 'completed' })).toBe(false);
        expect(showsResumeEntry({ ...base, recovery: { status: 'non_resumable', reason: null, resumable: false } })).toBe(false);
        expect(showsResumeEntry({ ...base, recovery: null })).toBe(false);
        expect(showsResumeEntry({ ...base, readOnly: true })).toBe(false);
    });
    it('用户消息、告警卡片与正在生成时不出现', () => {
        expect(showsResumeEntry({ ...base, isUser: true })).toBe(false);
        expect(showsResumeEntry({ ...base, isAlertCard: true })).toBe(false);
        expect(showsResumeEntry({ ...base, isGenerating: true })).toBe(false);
    });
});
