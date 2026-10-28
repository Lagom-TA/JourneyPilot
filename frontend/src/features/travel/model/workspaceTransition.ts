export type WorkspaceContentMode = 'cards' | 'conversation' | 'today';

export interface WorkspaceScene {
  mode: WorkspaceContentMode;
  day: number | null;
}

export interface WorkspaceSceneTransition {
  kind: 'same' | 'peer' | 'detail';
  direction: -1 | 0 | 1;
}

export function resolveWorkspaceSceneTransition(
  previous: WorkspaceScene,
  next: WorkspaceScene,
): WorkspaceSceneTransition {
  if (previous.mode === next.mode && previous.day === next.day) {
    return { kind: 'same', direction: 0 };
  }
  if (next.mode === 'conversation') return { kind: 'detail', direction: 1 };
  if (previous.mode === 'conversation') return { kind: 'detail', direction: -1 };
  if (previous.mode !== next.mode) return { kind: 'peer', direction: 0 };
  if (previous.mode !== 'cards') return { kind: 'same', direction: 0 };
  if (previous.day == null && next.day != null) return { kind: 'detail', direction: 1 };
  if (previous.day != null && next.day == null) return { kind: 'detail', direction: -1 };
  if (previous.day != null && next.day != null) {
    return { kind: 'detail', direction: next.day >= previous.day ? 1 : -1 };
  }
  return { kind: 'peer', direction: 0 };
}
