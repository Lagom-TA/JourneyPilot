import React from 'react';
import { ThinkingOrb, type OrbState } from 'thinking-orbs';
import { ORB_LABELS } from '../../lib/orbState';
import { cn } from '../../lib/utils';

interface AgentOrbProps {
  state: OrbState;
  /** 两个调过的尺寸：64 是头像级、20 是行内级。不是缩放，是两套点阵。 */
  size?: 20 | 64;
  paused?: boolean;
  className?: string;
  /** 覆盖默认的按状态可读名 */
  label?: string;
}

/**
 * 「agent 正在做什么」的活动球。全站只从这里拿 `ThinkingOrb`：
 *
 * - 主题**钉死 `light`**。产品目前只有一张浅色纸，而库的 `auto` 要靠祖先上的
 *   `data-theme` 或系统偏好推断 —— 系统偏好是深色时会在奶油纸上画出白点。真要做
 *   深色模式那天，把这一处改成 `auto` 并在 `<html>` 上挂 `data-theme`，别处不用动。
 * - 库自带 `role="img"`、按状态的 `aria-label`、`prefers-reduced-motion` 静帧、
 *   离屏与后台标签页自动暂停；这里只把 `aria-label` 换成产品自己的措辞。
 */
export const AgentOrb: React.FC<AgentOrbProps> = ({ state, size = 20, paused, className, label }) => (
  <ThinkingOrb
    state={state}
    size={size}
    theme="light"
    paused={paused}
    aria-label={label ?? ORB_LABELS[state]}
    className={cn('agent-orb shrink-0', className)}
  />
);
