export interface StopRunUiState {
  inputMode: 'normal' | 'stopped';
  markLastInterrupted: boolean;
}

/** 停止行为只改变输入区形态与最后一条回答的完成标记，不改写其它会话状态。 */
export function stopRunUiState(input: {
  hasRun: boolean;
  accepted: boolean;
  hadPendingDecision: boolean;
}): StopRunUiState {
  const markLastInterrupted = input.accepted && !input.hadPendingDecision;
  if (input.hasRun && input.accepted) {
    return { inputMode: 'stopped', markLastInterrupted };
  }
  return { inputMode: 'normal', markLastInterrupted };
}
