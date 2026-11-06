import { describe, expect, it } from 'vitest';
import { getChatErrorGuidance } from './chatErrorGuidance';

describe('getChatErrorGuidance', () => {
    it('guides an already executing run to its current state', () => {
        const guidance = getChatErrorGuidance('请求失败：409 run_already_executing private-server-detail', 'fault');
        expect(guidance.description).toContain('查看这趟旅行当前的规划进度');
        expect(guidance.action).toBe('reload');
        expect(JSON.stringify(guidance)).not.toContain('private-server-detail');
    });

    it('distinguishes known version conflicts from an unknown 409', () => {
        expect(getChatErrorGuidance('409 bundle_revision_conflict', 'fault').title).toBe('这次旅行结果刚刚更新过');
        const gate = getChatErrorGuidance('409 plan_gate_version_stale', 'fault');
        expect(gate.title).toBe('需要重新确认规划信息');
        expect(gate.description).toContain('确认信息缺失或已过期');
        expect(gate.action).toBe('reload');
        const unknown = getChatErrorGuidance('请求失败：409 private-server-detail', 'fault');
        expect(unknown.title).toBe('这次操作暂时无法执行');
        expect(unknown.action).toBe('reload');
        expect(JSON.stringify(unknown)).not.toContain('private-server-detail');
    });
});
