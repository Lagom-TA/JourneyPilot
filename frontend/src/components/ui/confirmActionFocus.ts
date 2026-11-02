export type ConfirmActionFocusTarget = 'confirm' | 'trigger' | null;

/** armed 时把焦点送进确认区；收起（超时/取消/完成）且焦点仍在确认区时还给触发键。 */
export function confirmActionFocusTarget(input: {
  armed: boolean;
  confirmPending: boolean;
  focusWithin: boolean;
}): ConfirmActionFocusTarget {
  if (input.armed && !input.confirmPending) return 'confirm';
  if (!input.armed && input.focusWithin) return 'trigger';
  return null;
}
