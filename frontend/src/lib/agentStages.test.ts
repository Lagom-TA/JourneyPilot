import { describe, expect, it } from 'vitest';

import { deriveStages, getStageIdForAgent } from './agentStages';
import type { ThinkingStep } from '../types/chat';

function step(agentName: string): ThinkingStep {
  return {
    id: agentName,
    agentName,
    content: '',
    stepName: agentName,
    timestamp: new Date('2026-01-01T00:00:00Z'),
  };
}

describe('agent stage projection', () => {
  it.each([
    ['当前中文节点', '候选校验', 'verify'],
    ['历史内部节点', 'delivery_finalizer', 'synthesis'],
    ['中文补研节点', '目的地调研（第2轮补充）', 'research'],
    ['内部补研节点', 'destination_researcher_r2', 'research'],
  ] as const)('%s 映射到 %s', (_label, agentName, stage) => {
    expect(getStageIdForAgent(agentName)).toBe(stage);
  });

  it('把实际节点投影到阶段状态并标记补研轮次', () => {
    const { stages, hasDeepWorkflow } = deriveStages(
      [step('候选校验'), step('目的地调研（第2轮补充）')],
      { isStreaming: true, isSynthesizing: false, answerStarted: false },
    );

    expect(hasDeepWorkflow).toBe(true);
    expect(stages.find((stage) => stage.id === 'verify')?.status).toBe('done');
    expect(stages.find((stage) => stage.id === 'research')).toMatchObject({
      status: 'active',
      refinementRound: 2,
    });
  });

  it('快答节点不进入深度阶段', () => {
    const { stages, hasDeepWorkflow } = deriveStages(
      [step('fast_answer_agent')],
      { isStreaming: true, isSynthesizing: false, answerStarted: false },
    );

    expect(getStageIdForAgent('fast_answer_agent')).toBeNull();
    expect(getStageIdForAgent('旅行顾问')).toBeNull();
    expect(hasDeepWorkflow).toBe(false);
    expect(stages.every((stage) => stage.status === 'pending')).toBe(true);
  });
});
