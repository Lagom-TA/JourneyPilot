import { describe, expect, it } from "vitest";
import { hideDeliveryReadyNotice, projectVisibleMessages } from "./conversationFlow";
import { type Message } from "../types/messages";
function message(id: string, role: Message['role'], content: string, extra: Partial<Message> = {}): Message {
    return { id, role, content, displayContent: content, timestamp: new Date(0), ...extra };
}
describe('hideDeliveryReadyNotice', () => {
    it('hides the redundant completion text without removing research steps', () => {
        const notice = message('a1', 'assistant', '旅行方案已保存，可以查看完整行程。', {
            thinkingSteps: [{ id: 'research', agentName: '研究', content: '查询资料', stepName: '调研', timestamp: new Date(0) }],
        });
        expect(hideDeliveryReadyNotice(notice)).toMatchObject({ content: '', displayContent: '', thinkingSteps: notice.thinkingSteps });
        expect(notice.content).toBe('旅行方案已保存，可以查看完整行程。');
    });
    it('preserves user messages, errors, and substantive assistant answers', () => {
        for (const item of [
            message('u1', 'user', '旅行方案已保存，可以查看完整行程。'),
            message('e1', 'assistant', '旅行方案已保存，可以查看完整行程。', { type: 'error' }),
            message('a2', 'assistant', '已经调整好第二天的行程。'),
            message('a3', 'assistant', '已经调整好第二天的行程。', { displayContent: '旅行方案已保存，可以查看完整行程。' }),
        ]) expect(hideDeliveryReadyNotice(item)).toBe(item);
    });
});
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
