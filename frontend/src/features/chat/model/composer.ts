export interface ComposerInput {
  isStreaming: boolean;
  hasInput: boolean;
  hasTripRun: boolean;
  runCancellable: boolean;
}

export interface ComposerState {
  action: 'send' | 'supplement' | 'stop';
  showStop: boolean;
  sendDisabled: boolean;
}

/**
 * 流式期间没有可取消 Trip Run（普通问答）时，主按钮应能停止本地流，
 * 而不是保持“发送”并静默丢弃输入。
 */
export function composerState(input: ComposerInput): ComposerState {
  if (input.isStreaming) {
    if (!input.hasTripRun || (input.runCancellable && !input.hasInput)) {
      return { action: 'stop', showStop: true, sendDisabled: false };
    }
    return { action: 'supplement', showStop: false, sendDisabled: !input.hasInput };
  }
  return { action: 'send', showStop: false, sendDisabled: !input.hasInput };
}
