import { describe, expect, it } from 'vitest';
import type { ThinkingStep } from '../types/chat';
import { deriveOrbState, orbStateForAgent } from './orbState';

const step = (agentName: string): ThinkingStep => ({
  id: agentName,
  agentName,
  content: '',
  stepName: agentName,
  timestamp: new Date('2026-01-01T00:00:00Z'),
});

const idle = { isStreaming: false, isSynthesizing: false, answerStarted: false };
const live = { isStreaming: true, isSynthesizing: false, answerStarted: false };

describe('orbStateForAgent', () => {
  it('内部名与显示名落在同一个球上', () => {
    expect(orbStateForAgent('transport_researcher')).toBe('connecting');
    expect(orbStateForAgent('交通查询')).toBe('connecting');
    expect(orbStateForAgent('itinerary_planner')).toBe('weaving');
    expect(orbStateForAgent('行程规划')).toBe('weaving');
  });

  it('补研轮次后缀不改变球', () => {
    expect(orbStateForAgent('destination_researcher_r2')).toBe('searching');
    expect(orbStateForAgent('目的地调研（第2轮补充）')).toBe('searching');
  });

  it('所有门都是 solving', () => {
    for (const gate of ['candidate_gate', 'artifact_gate', 'intent_fidelity_gate', 'delivery_quality_gate']) {
      expect(orbStateForAgent(gate)).toBe('solving');
    }
  });

  it('未登记但有阶段的节点退回阶段默认；完全未知退回 working', () => {
    expect(orbStateForAgent('completely_unknown_node')).toBe('working');
  });
});

describe('deriveOrbState', () => {
  it('等待用户时呼吸，优先于任何步', () => {
    expect(deriveOrbState([step('destination_researcher')], { ...live, awaitingInput: true })).toBe('breathing');
  });

  it('最终回答开始后是 composing', () => {
    expect(deriveOrbState([step('candidate_gate')], { ...live, answerStarted: true })).toBe('composing');
    expect(deriveOrbState([step('candidate_gate')], { ...live, isSynthesizing: true })).toBe('composing');
  });

  it('取最近一个有名字的步', () => {
    const steps = [step('planner'), step('destination_researcher'), step('transport_researcher')];
    expect(deriveOrbState(steps, live)).toBe('connecting');
  });

  it('刚开始没有步时是 listening，静止时是 breathing', () => {
    expect(deriveOrbState([], live)).toBe('listening');
    expect(deriveOrbState([], idle)).toBe('breathing');
  });
});
