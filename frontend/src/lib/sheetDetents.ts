export type SheetDetent = 55 | 92;
export type SheetAnchor = SheetDetent | 0;

const PROJECTION_WINDOW_S = 0.2;
const FLICK_VELOCITY = 900;

export function sheetOffset(height: number, detent: SheetAnchor): number {
  return height * (1 - detent / 92);
}

// 快速下划逐档退出；慢速拖动根据释放位置与惯性选择最近停靠位。
export function releaseSheet(
  height: number,
  position: number,
  velocity: number,
  current: SheetDetent,
): SheetAnchor {
  if (velocity > FLICK_VELOCITY) return current === 92 ? 55 : 0;
  if (velocity < -FLICK_VELOCITY) return 92;
  const projected = position + velocity * PROJECTION_WINDOW_S;
  return ([92, 55, 0] as const).reduce<SheetAnchor>((best, anchor) => (
    Math.abs(sheetOffset(height, anchor) - projected) < Math.abs(sheetOffset(height, best) - projected)
      ? anchor
      : best
  ), 92);
}
