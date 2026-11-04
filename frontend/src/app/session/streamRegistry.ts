import type { AppState } from '../state/state';
import type { ActiveStreamHandle } from './runtimeSnapshot';

export function findSessionStream(
  streams: Map<string, ActiveStreamHandle>,
  sessionId: string | null,
  conversationEpoch: number,
): ActiveStreamHandle | undefined {
  return [...streams.values()].find(stream => sessionId
    ? stream.sessionId === sessionId
    : stream.sessionId === null && stream.conversationEpoch === conversationEpoch);
}

export function abortSessionStream(streams: Map<string, ActiveStreamHandle>, state: AppState): void {
  findSessionStream(streams, state.currentSessionId, state.conversationEpoch)?.controller?.abort();
}

export function pendingStreamCacheKey(token: string): string {
  return `\u0000${token}`;
}
