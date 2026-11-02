import { generateId } from './utils';

/** crypto.randomUUID 只在安全上下文可用；缺失时退回本地随机标识。 */
export function randomId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ?? generateId();
}

/**
 * 把文本写入剪贴板。浏览器可能在非安全上下文或用户拒绝时抛错，
 * 调用方据此展示可读的失败提示，而不是产生未处理的 rejection。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    const clipboard = globalThis.navigator?.clipboard;
    if (!clipboard?.writeText) return false;
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
