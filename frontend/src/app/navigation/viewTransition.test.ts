import { describe, expect, it } from 'vitest';
import { resolveViewTransition } from './viewTransition';

describe('resolveViewTransition', () => {
  it('keeps the same view still', () => {
    expect(resolveViewTransition('chat', 'chat', true)).toEqual({ kind: 'same', direction: 0 });
  });

  it('follows peer navigation order in both directions', () => {
    expect(resolveViewTransition('user-preferences', 'presets', false)).toEqual({ kind: 'peer', direction: 1 });
    expect(resolveViewTransition('knowledge-base', 'trips', false)).toEqual({ kind: 'peer', direction: -1 });
  });

  it('distinguishes entering a trip from returning to the trip list', () => {
    expect(resolveViewTransition('trips', 'chat', false)).toEqual({ kind: 'detail', direction: 1 });
    expect(resolveViewTransition('chat', 'trips', false)).toEqual({ kind: 'detail', direction: -1 });
  });

  it('uses a neutral transition when a new conversation resets the workspace', () => {
    expect(resolveViewTransition('trips', 'chat', true)).toEqual({ kind: 'reset', direction: 0 });
    expect(resolveViewTransition('presets', 'chat', true)).toEqual({ kind: 'reset', direction: 0 });
  });
});
