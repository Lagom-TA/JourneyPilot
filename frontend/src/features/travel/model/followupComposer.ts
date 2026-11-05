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
      : '',
    placeholder: PLACEHOLDER,
  };
}
