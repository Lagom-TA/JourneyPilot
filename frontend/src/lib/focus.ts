/** 循环焦点陷阱的下一个下标；current=-1 时从头/尾进入。 */
export function nextTrapIndex(current: number, length: number, backwards: boolean): number {
  if (length <= 0) return 0;
  if (current < 0 || current >= length) return backwards ? length - 1 : 0;
  return backwards ? (current - 1 + length) % length : (current + 1) % length;
}

export function focusableIn(container: HTMLElement): HTMLElement[] {
  const nodes = container.querySelectorAll<HTMLElement>(
    'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
  );
  return [...nodes].filter((node) => node.offsetParent !== null);
}
