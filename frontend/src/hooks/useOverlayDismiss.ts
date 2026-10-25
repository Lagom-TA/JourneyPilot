import { useEffect, useRef } from 'react';


/* 只有最后打开的浮层响应 Esc，避免嵌套浮层同时关闭。 */
const openOverlays: symbol[] = [];

interface OverlayDismissOptions {
  open: boolean;
  onDismiss: () => void;
  /* 传入面板 ref 时会移动焦点；面板需允许程序化聚焦。 */
  panelRef?: React.RefObject<HTMLElement>;
}

export function useOverlayDismiss({ open, onDismiss, panelRef }: OverlayDismissOptions): void {
  // 回调使用 ref，避免渲染时重挂 effect 改变嵌套浮层栈序。
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;

  useEffect(() => {
    if (!open) return undefined;

    const id = Symbol('overlay');
    openOverlays.push(id);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (openOverlays[openOverlays.length - 1] !== id) return;
      event.preventDefault();
      onDismissRef.current();
    };
    document.addEventListener('keydown', onKeyDown);

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      const index = openOverlays.indexOf(id);
      if (index >= 0) openOverlays.splice(index, 1);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;

    const opener = document.activeElement as HTMLElement | null;

    if (panelRef) {
      // 延迟一帧，让子元素 autoFocus 先完成；焦点已在面板内时不移动。
      const frame = requestAnimationFrame(() => {
        const panel = panelRef.current;
        if (panel && !panel.contains(document.activeElement)) panel.focus();
      });
      return () => {
        cancelAnimationFrame(frame);
        if (opener && document.contains(opener)) opener.focus();
      };
    }

    return () => {
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [open]);
}
