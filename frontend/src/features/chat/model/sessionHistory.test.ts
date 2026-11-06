import { describe, expect, it } from "vitest";
import { latestAssistantThinkingSteps } from "./sessionHistory";
import { type Message, type ThinkingStep } from "../types/messages";

const step = (id: string): ThinkingStep => ({
    id,
    agentName: '目的地调研',
    content: '',
    stepName: '',
    timestamp: new Date('2026-01-01T00:00:00Z'),
});
const assistant = (id: string, runId: string | undefined, steps: ThinkingStep[]): Message => ({
    id,
    role: 'assistant',
    content: '',
    displayContent: '',
    timestamp: new Date('2026-01-01T00:00:00Z'),
    runId,
    thinkingSteps: steps,
});

describe('run-scoped session history', () => {
    it('只取当前 Run 的助手步骤，不把父 Run 记录混进子 Run', () => {
        const messages = [
            assistant('parent', 'run-parent', [step('parent-step')]),
            assistant('child', 'run-child', [step('child-step')]),
        ];
        expect(latestAssistantThinkingSteps(messages, 'run-child').map(item => item.id)).toEqual(['child-step']);
        expect(latestAssistantThinkingSteps(messages, 'run-parent').map(item => item.id)).toEqual(['parent-step']);
    });
    it('没有匹配 Run 时返回空记录，而不是借用别的 Run', () => {
        const messages = [assistant('parent', 'run-parent', [step('parent-step')])];
        expect(latestAssistantThinkingSteps(messages, 'run-missing')).toEqual([]);
    });
    it('未指定 Run 时取最新一条助手消息的步骤', () => {
        const messages = [
            assistant('older', 'run-a', [step('older-step')]),
            assistant('latest', 'run-b', [step('latest-step')]),
        ];
        expect(latestAssistantThinkingSteps(messages).map(item => item.id)).toEqual(['latest-step']);
    });
    it('同一次 Run 续跑复用助手消息 id 时合并各 turn 的步骤', () => {
        // 续跑会新建 turn 但复用 assistant_message_id；历史按 turn 投影后
        // 同一助手消息分成两条，各自只带本 turn 的步骤。
        const messages = [
            assistant('same-message', 'run-1', [step('before-resume')]),
            assistant('same-message', 'run-1', [step('after-resume')]),
        ];
        expect(latestAssistantThinkingSteps(messages, 'run-1').map(item => item.id)).toEqual([
            'before-resume',
            'after-resume',
        ]);
    });
});
