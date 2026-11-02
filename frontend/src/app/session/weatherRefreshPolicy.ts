import { ApiError } from '../../lib/http';

export const MAX_REFRESH_ATTEMPTS = 3;

export function shouldStartWeatherRefresh(input: {
  enabled: boolean;
  bundleId: string | null;
  attempted: ReadonlySet<string>;
  inFlight: ReadonlySet<string>;
}): boolean {
  return Boolean(input.enabled && input.bundleId && !input.attempted.has(input.bundleId) && !input.inFlight.has(input.bundleId));
}

export function shouldRetryWeatherRefresh(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 429 || error.status >= 500;
}

export function weatherRetryDelayMs(attempt: number): number {
  return 150 * 2 ** (attempt - 1);
}
