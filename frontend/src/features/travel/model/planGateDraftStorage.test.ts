import { afterEach, describe, expect, it, vi } from 'vitest';
import { planGateDraftKey, readPlanGateDraft, writePlanGateDraft } from './planGateDraftStorage';

describe('plan gate answer drafts', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('keeps drafts isolated by session, run and exact gate version', () => {
        const values = new Map<string, string>();
        vi.stubGlobal('sessionStorage', {
            getItem: (key: string) => values.get(key) ?? null,
            setItem: (key: string, value: string) => values.set(key, value),
            removeItem: (key: string) => values.delete(key),
        });
        const first = planGateDraftKey('session-a', 'run-a', 'version-1');
        const nextVersion = planGateDraftKey('session-a', 'run-a', 'version-2');
        const nextRun = planGateDraftKey('session-a', 'run-b', 'version-1');
        expect(writePlanGateDraft(first, '需要无障碍交通')).toBe(true);
        expect(readPlanGateDraft(first).value).toBe('需要无障碍交通');
        expect(readPlanGateDraft(nextVersion).value).toBe('');
        expect(readPlanGateDraft(nextRun).value).toBe('');
        expect(writePlanGateDraft(first, '')).toBe(true);
        expect(readPlanGateDraft(first).value).toBe('');
    });

    it('reports unavailable storage instead of claiming the answer was saved', () => {
        vi.stubGlobal('sessionStorage', {
            getItem: () => { throw new Error('blocked'); },
            setItem: () => { throw new Error('blocked'); },
        });
        const key = planGateDraftKey('session', 'run', 'version');
        expect(readPlanGateDraft(key)).toEqual({ value: '', available: false });
        expect(writePlanGateDraft(key, '回答')).toBe(false);
        expect(planGateDraftKey('session', 'run')).toBeNull();
        expect(planGateDraftKey('session', 'run', '\ud800')).toBeNull();
    });
});
