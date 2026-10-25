import { describe, expect, it } from "vitest";
import { projectVisibleMessages } from "./conversationFlow";
import { type Message } from "../types/messages";
function message(id: string, role: Message['role'], content: string, extra: Partial<Message> = {}): Message {
    return { id, role, content, displayContent: content, timestamp: new Date(0), ...extra };
}
describe('projectVisibleMessages', () => {
    const currentRun = [
        message('u1', 'user', '去京都玩五天'),
        message('a1', 'assistant', '几个人出行？'),
        message('u2', 'user', '开始调研'),
        message('a2', 'assistant', '行程已生成'),
    ];
    it('hides the current run setup exchange', () => {
        expect(projectVisibleMessages(currentRun).map((m) => m.id)).toEqual(['a2']);
    });
    it('keeps history loaded by paging above that boundary', () => {
        const withHistory = [
            message('h1', 'user', '上个月去了大阪', { isEarlierHistory: true }),
            message('h2', 'assistant', '那次的行程在这里', { isEarlierHistory: true }),
            ...currentRun,
        ];
        expect(projectVisibleMessages(withHistory).map((m) => m.id)).toEqual(['h1', 'h2', 'a2']);
    });
    it('keeps a compaction event from the setup range', () => {
        const withCompaction = [
            message('c1', 'assistant', '较早的对话已整理', { type: 'context_compaction' }),
            ...currentRun,
        ];
        expect(projectVisibleMessages(withCompaction).map((m) => m.id)).toEqual(['c1', 'a2']);
    });
    it('treats a pending plan gate as the boundary before research starts', () => {
        const beforeResearch = [
            message('u1', 'user', '去京都玩五天'),
            message('a1', 'assistant', '几个人出行？'),
            message('u2', 'user', '两个人'),
        ];
        expect(projectVisibleMessages(beforeResearch, { planGatePending: true })).toEqual([]);
        expect(projectVisibleMessages(beforeResearch).map((m) => m.id)).toEqual(['u1', 'a1', 'u2']);
    });
});
