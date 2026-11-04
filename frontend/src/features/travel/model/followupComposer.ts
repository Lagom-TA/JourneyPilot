import { type TripRunStatus } from '../types/runs';

/**
 * 生成过程的可写终态。等待问题和方案确认由对应交互处理。
 */
const FOLLOWUP_STATUSES: readonly TripRunStatus[] = ['completed', 'failed', 'cancelled', 'interrupted'];

export interface FollowupComposerInput {
  runStatus: TripRunStatus | null;
  isStreaming: boolean;
  hasDelivery: boolean;
  readOnly: boolean;
  gatePending: boolean;
  pendingUnderstanding: boolean;
  pendingRouteConfirmation: boolean;
  canResume?: boolean;
}

export interface FollowupComposerState {
  visible: boolean;
  hint: string;
  placeholder: string;
}

const PLACEHOLDER = '继续补充要求，例如：第二天少安排一个景点';

function hintFor(runStatus: TripRunStatus, canResume: boolean): string {
  if (runStatus === 'completed') return '规划已生成。可以继续补充要求，我会接着完善这趟旅行。';
  if (runStatus === 'failed') return '这次规划没有完成。可以继续补充要求，或从左侧返回新旅行。';
  if (runStatus === 'cancelled') return '这次规划已取消。可以继续补充要求，或从左侧返回新旅行。';
  return canResume
    ? '规划已中断。可以继续补充要求，或从左侧从最近的位置继续。'
    : '规划已中断。可以继续补充要求，或从左侧返回新旅行。';
}

export function followupComposerState(input: FollowupComposerInput): FollowupComposerState {
  const terminal = input.runStatus !== null && FOLLOWUP_STATUSES.includes(input.runStatus);
  const visible = Boolean(
    (input.isStreaming
      ? input.hasDelivery
      : terminal || (input.hasDelivery && input.runStatus === 'running'))
    && !input.readOnly
    && !input.gatePending
    && !input.pendingUnderstanding
    && !input.pendingRouteConfirmation,
  );
  return {
    visible,
    hint: input.isStreaming && input.hasDelivery
      ? '新消息会在当前回复结束后一起发送。'
      : terminal ? hintFor(input.runStatus as TripRunStatus, input.canResume === true) : '',
    placeholder: PLACEHOLDER,
  };
}
