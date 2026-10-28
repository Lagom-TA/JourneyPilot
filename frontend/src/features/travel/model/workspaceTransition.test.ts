import { describe, expect, it } from 'vitest';
import { resolveWorkspaceSceneTransition, type WorkspaceScene } from './workspaceTransition';

const scene = (mode: WorkspaceScene['mode'], day: number | null = null): WorkspaceScene => ({ mode, day });

describe('resolveWorkspaceSceneTransition', () => {
  it('keeps the current scene stable', () => {
    expect(resolveWorkspaceSceneTransition(scene('cards', 1), scene('cards', 1))).toEqual({ kind: 'same', direction: 0 });
  });

  it('treats overview and day details as forward and backward navigation', () => {
    expect(resolveWorkspaceSceneTransition(scene('cards'), scene('cards', 2))).toEqual({ kind: 'detail', direction: 1 });
    expect(resolveWorkspaceSceneTransition(scene('cards', 2), scene('cards'))).toEqual({ kind: 'detail', direction: -1 });
  });

  it('uses chronological directions between days', () => {
    expect(resolveWorkspaceSceneTransition(scene('cards', 1), scene('cards', 3))).toEqual({ kind: 'detail', direction: 1 });
    expect(resolveWorkspaceSceneTransition(scene('cards', 3), scene('cards', 1))).toEqual({ kind: 'detail', direction: -1 });
  });

  it('enters and leaves conversation without mixing in the day direction', () => {
    expect(resolveWorkspaceSceneTransition(scene('cards', 2), scene('conversation', 2))).toEqual({ kind: 'detail', direction: 1 });
    expect(resolveWorkspaceSceneTransition(scene('conversation', 2), scene('cards', 2))).toEqual({ kind: 'detail', direction: -1 });
  });

  it('treats today as a peer view without horizontal travel', () => {
    expect(resolveWorkspaceSceneTransition(scene('cards', 2), scene('today', 2))).toEqual({ kind: 'peer', direction: 0 });
  });
});
