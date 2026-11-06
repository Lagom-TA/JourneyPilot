import { describe, expect, it } from 'vitest';
import { getChatErrorGuidance } from './chatErrorGuidance';

describe('getChatErrorGuidance', () => {
    it('routes an executing run to reload without exposing private details', () => {
        const guidance = getChatErrorGuidance('请求失败：409 run_already_executing private-server-detail', 'fault');
        expect(guidance.action).toBe('reload');
        expect(JSON.stringify(guidance)).not.toContain('private-server-detail');
    });

    it('keeps version-conflict recovery actions distinct from unknown 409s', () => {
        const bundle = getChatErrorGuidance('409 bundle_revision_conflict', 'fault');
        expect(bundle.action).toBeNull();
        const gate = getChatErrorGuidance('409 plan_gate_version_stale', 'fault');
        expect(gate.action).toBe('reload');
        const unknown = getChatErrorGuidance('请求失败：409 private-server-detail', 'fault');
        expect(unknown.action).toBe('reload');
        expect(JSON.stringify(unknown)).not.toContain('private-server-detail');
    });
});
