import { describe, expect, it } from 'vitest';
import { confirmActionFocusTarget } from './confirmActionFocus';

describe('confirmActionFocusTarget', () => {
  it('moves focus into the confirmation when armed', () => {
    expect(confirmActionFocusTarget({ armed: true, confirmPending: false, focusWithin: false })).toBe('confirm');
  });

  it('returns focus to the trigger after disarm when it was in the confirmation', () => {
    expect(confirmActionFocusTarget({ armed: false, confirmPending: false, focusWithin: true })).toBe('trigger');
  });

  it('leaves focus alone when it is outside the confirmation', () => {
    expect(confirmActionFocusTarget({ armed: false, confirmPending: false, focusWithin: false })).toBeNull();
  });
});
