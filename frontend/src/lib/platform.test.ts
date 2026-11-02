import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyText, randomId } from './platform';

afterEach(() => vi.unstubAllGlobals());

describe('randomId', () => {
  it('uses crypto.randomUUID when it is available', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'uuid-1' });
    expect(randomId()).toBe('uuid-1');
  });

  it('falls back without throwing when the secure-context API is missing', () => {
    vi.stubGlobal('crypto', {});
    const value = randomId();
    expect(typeof value).toBe('string');
    expect(value.length).toBeGreaterThan(0);
  });
});

describe('copyText', () => {
  it('returns true when the clipboard accepts the text', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    await expect(copyText('hello')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('returns false instead of throwing when the clipboard is missing or denied', async () => {
    vi.stubGlobal('navigator', {});
    await expect(copyText('hello')).resolves.toBe(false);
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    await expect(copyText('hello')).resolves.toBe(false);
  });
});
