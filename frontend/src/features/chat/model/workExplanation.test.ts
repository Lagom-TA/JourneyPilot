import { describe, expect, it } from 'vitest';
import { appReducer } from '../../../app/state/appReducer';
import { initialState } from '../../../app/state/initialState';
import type { AppState } from '../../../app/state/state';
import { createStreamPresentation } from './streamPresentation';
import { getActivityStageIdForAgent, deriveActivityStages } from './agentStages';
import { isWorkExplanationStep, researchGroups, workExplanationText } from './researchProgress';
import { mapThinkingSteps } from './sessionHistory';
import type { ThinkingStep } from '../types/messages';
import type { SSEEvent } from '../types/events';
import type { StreamFrameBatch } from './streamFrameBatch';
import type { ChatAction } from './state';

const step = (agentName: string, extra: Partial<ThinkingStep> = {}): ThinkingStep => ({
    id: agentName, agentName, content: '', stepName: '', timestamp: new Date(), ...extra,
});
const note = (extra: Partial<ThinkingStep> = {}): ThinkingStep => step('目的地调研', {
    id: 'work-note:r', kind: 'work_explanation', content: '我先确认一下地点。',
    round: 1, callId: 'llm_1', seq: 0, endTime: new Date(), ...extra,
});


describe("public work explanation", () => {
    it("upserts a stable note step and preserves stage ownership", () => {
        const actions: ChatAction[] = [];
        const frame = { queueUsage() {}, queueAssistantUpdate() {} } as unknown as StreamFrameBatch;
        const presentation = createStreamPresentation(action => actions.push(action), { id: "m", role: "assistant", content: "", displayContent: "", timestamp: new Date() }, undefined, frame);
        const event = { type: "work_explanation", step_id: "work-note:r", agent_name: "目的地调研", content: "我先确认一下地点。", round: 1, call_id: "llm_1", seq: 0 } as SSEEvent;
        expect(presentation.handle(event)).toBe(true);
        presentation.handle(event);
        const upserts = actions.filter(action => action.type === "UPSERT_THINKING_STEP");
        expect(upserts).toHaveLength(2);
        expect(upserts[0].payload).toMatchObject({ id: "work-note:r", kind: "work_explanation", agentName: "目的地调研", round: 1, seq: 0 });
    });

    it("dedupes by step id and keeps notes out of group completion", () => {
        const state = { ...initialState, thinkingSteps: [], currentMessages: [] } as AppState;
        const first = appReducer(state, { type: "UPSERT_THINKING_STEP", payload: note() });
        const second = appReducer(first, { type: "UPSERT_THINKING_STEP", payload: note({ content: "更新后的说明。" }) });
        expect(second.thinkingSteps).toHaveLength(1);
        expect(second.thinkingSteps[0].content).toBe("更新后的说明。");
        expect(getActivityStageIdForAgent("目的地调研")).toBe("research");
        const groups = researchGroups([step("目的地调研", { progressStatus: "running" }), note()], true, false);
        expect(groups[0].stage).toBe("research");
        expect(groups[0].status).toBe("running");
        // 历史记录中的说明自带结束时间，单靠说明不能结束仍在运行的调研。
        expect(researchGroups([note()], true, false)[0].status).toBe("running");
        expect(isWorkExplanationStep(note())).toBe(true);
        expect(workExplanationText("x".repeat(200))).toHaveLength(160);
    });

    it("keeps saved note metadata and attributes it to research", () => {
        const mapped = mapThinkingSteps([{ id: "work-note:r", agent_name: "目的地调研", content: "我先确认一下地点。", step_name: "工作说明", timestamp: "2026-11-02T00:00:00Z", kind: "work_explanation", round: 1, call_id: "llm_1", seq: 0 }]);
        expect(mapped[0]).toMatchObject({ kind: "work_explanation", round: 1, callId: "llm_1", seq: 0 });
        const projection = deriveActivityStages([note()], { isStreaming: false, isSynthesizing: false, answerStarted: false, runStatus: "running" });
        expect(projection.currentStage).toBe("research");
    });
});
