import { type TripRunStatus } from '../types/runs';

/**
 * 生成过程的可写终态。此时过程已停止产生新事件，可以在同一工作台继续补充要求。
 * awaiting_input 由计划门或理解问题自己承担输入，running／cancel_requested 仍在进行中。
 */
const FOLLOWUP_STATUSES: readonly TripRunStatus[] = ['completed', 'failed', 'cancelled', 'interrupted'];

export interface FollowupComposerInput {
  runStatus: TripRunStatus | null;
  isStreaming: boolean;
  readOnly: boolean;
  gatePending: boolean;
  pendingUnderstanding: boolean;
  pendingRouteConfirmation: boolean;
  canResume?: boolean;
  hasUnresolved?: boolean;
}

export interface FollowupComposerState {
  visible: boolean;
  hint: string;
  placeholder: string;
}

const PLACEHOLDER = '继续补充要求，例如：第二天少安排一个景点';

function hintFor(runStatus: TripRunStatus, canResume: boolean): string {
  if (runStatus === 'completed') return '规划已完成。可以继续补充要求，我会接着完善这趟旅行。';
  if (runStatus === 'failed') return '这次规划没有完成。可以继续补充要求，或从左侧返回新旅行。';
  if (runStatus === 'cancelled') return '这次规划已取消。可以继续补充要求，或从左侧返回新旅行。';
  return canResume
    ? '规划已中断。可以继续补充要求，或从左侧从最近的位置继续。'
    : '规划已中断。可以继续补充要求，或从左侧返回新旅行。';
}

export function followupComposerState(input: FollowupComposerInput): FollowupComposerState {
  const terminal = input.runStatus !== null && FOLLOWUP_STATUSES.includes(input.runStatus);
  const visible = Boolean(
    terminal
    && !input.isStreaming
    && !input.readOnly
    && !input.gatePending
    && !input.pendingUnderstanding
    && !input.pendingRouteConfirmation,
  );
  return {
    visible,
    hint: terminal
      ? input.runStatus === 'completed' && input.hasUnresolved
        ? '部分行程尚未安排，可以继续补充要求。'
        : hintFor(input.runStatus as TripRunStatus, input.canResume === true)
      : '',
    placeholder: PLACEHOLDER,
  };
}
