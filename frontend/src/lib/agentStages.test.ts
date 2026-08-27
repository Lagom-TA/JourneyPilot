import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  AGENT_TO_STAGE,
  NON_WORKFLOW_NODES,
  deriveStages,
  getStageIdForAgent,
} from './agentStages';
import type { ThinkingStep } from '../types/chat';

/**
 * 这一批钉住的是**跨语言的那道界**：后端每发一个 `agent_name`，界面这边都要知道它
 * 属于哪个责任阶段。少一个的后果不是「少一行」，是**那一阶段永远亮不起来** ——
 * `getStageIdForAgent` 返回 null，`deriveStages` 直接 `continue` 跳过这个 step，
 * 时间线上那一格一直停在 pending，而没有任何测试会红。
 *
 * 这不是假想。修这一批之前，中文那半漂在四个后端从来没发过的名字上
 * （`候选准入` / `交付质量` / `交付投影` / `原子交付`，`git log -S` 在
 * `display_names.py` 里查不到任何提交），于是「准入」这一格在真实会话里从未点亮过。
 *
 * 所以这里不写死一份期望清单，而是**去读后端那个文件**：两张表的差集必须为空，
 * 而且这个断言在任何一侧改动时都会响。后端那张表覆盖图上每个节点由 INV-NODE-001
 * 保证，两条接起来就是「图上每个节点都进得了时间线」。
 */

/** 后端 `AGENT_DISPLAY_NAMES` 的 内部名 → 中文显示名。 */
function backendDisplayNames(): Map<string, string> {
  const here = fileURLToPath(new URL('.', import.meta.url));
  const source = readFileSync(
    `${here}../../../src/travel_agent/utils/display_names.py`,
    'utf-8',
  );
  const table = source.match(/AGENT_DISPLAY_NAMES[^{]*\{([\s\S]*?)\n\}/);
  if (!table) {
    throw new Error(
      '在 display_names.py 里找不到 AGENT_DISPLAY_NAMES —— 后端那张表被改名或改了写法，' +
        '这条守卫要跟着改，不能当成「没问题」。',
    );
  }
  const names = new Map<string, string>();
  for (const match of table[1].matchAll(/"([a-z_]+)":\s*"([^"]+)"/g)) {
    names.set(match[1], match[2]);
  }
  return names;
}

describe('责任阶段表与后端显示名表', () => {
  it('解析得到的后端表规模合理（解析器坏了就不是零，是这一条先红）', () => {
    // 一个解析出零条的正则会让下面每一条差集断言都恒真。
    expect(backendDisplayNames().size).toBeGreaterThanOrEqual(20);
  });

  it('后端会发的每一个名字，界面都知道它属于哪一阶段', () => {
    const missing: string[] = [];
    for (const [node, display] of backendDisplayNames()) {
      if (NON_WORKFLOW_NODES.has(node)) continue;
      if (!(node in AGENT_TO_STAGE)) missing.push(`${node}（内部名）`);
      if (!(display in AGENT_TO_STAGE)) missing.push(`${display}（${node} 的显示名）`);
    }
    expect(
      missing,
      '这些名字后端会发、界面没有阶段映射，它们的 step 会被静默跳过：\n' +
        missing.join('\n'),
    ).toEqual([]);
  });

  it('界面这边没有后端从不发送的名字', () => {
    const backend = backendDisplayNames();
    const known = new Set([...backend.keys(), ...backend.values()]);
    const stale = Object.keys(AGENT_TO_STAGE).filter((key) => !known.has(key));
    expect(
      stale,
      '这些键后端从来不发，留着只会让人以为那一阶段有人管：' + stale.join('、'),
    ).toEqual([]);
  });

  it('同一个节点的内部名与显示名落在同一阶段', () => {
    const disagreeing: string[] = [];
    for (const [node, display] of backendDisplayNames()) {
      if (NON_WORKFLOW_NODES.has(node)) continue;
      if (AGENT_TO_STAGE[node] !== AGENT_TO_STAGE[display]) {
        disagreeing.push(
          `${node} → ${AGENT_TO_STAGE[node]}，但 ${display} → ${AGENT_TO_STAGE[display]}`,
        );
      }
    }
    expect(disagreeing, '历史会话与当前会话会被画到不同格子里：\n' + disagreeing.join('\n')).toEqual([]);
  });

  it('不收进时间线的节点逐个列了理由，不是一个空集', () => {
    // 空集会让上面那条「都知道属于哪一阶段」的例外口子变成静默通行证。
    expect([...NON_WORKFLOW_NODES]).toEqual(['fast_answer_agent']);
    expect(getStageIdForAgent('fast_answer_agent')).toBeNull();
    expect(getStageIdForAgent('旅行顾问')).toBeNull();
  });
});

describe('回归：这一批修掉的两个具体格子', () => {
  function step(agentName: string): ThinkingStep {
    return { agentName, timestamp: new Date('2026-01-01T00:00:00Z') } as ThinkingStep;
  }

  it('候选校验点亮「准入」——修之前它对应的键是 `候选准入`，从未被发送过', () => {
    expect(getStageIdForAgent('候选校验')).toBe('verify');
    const { stages } = deriveStages([step('候选校验')], {
      isStreaming: false,
      isSynthesizing: false,
      answerStarted: false,
    });
    expect(stages.find((s) => s.id === 'verify')?.status).not.toBe('pending');
  });

  it('交付定稿仍落在「交付」——后端补了中文名之后，只认英文键的旧表会漏掉它', () => {
    expect(getStageIdForAgent('交付定稿')).toBe('synthesis');
    // 历史会话里存的是更早那版的内部名，同样要认得。
    expect(getStageIdForAgent('delivery_finalizer')).toBe('synthesis');
  });

  it('补研轮次后缀不影响阶段归属', () => {
    expect(getStageIdForAgent('目的地调研（第2轮补充）')).toBe('research');
    expect(getStageIdForAgent('destination_researcher_r2')).toBe('research');
  });
});
