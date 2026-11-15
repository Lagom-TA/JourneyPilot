import { useCallback } from 'react';
import { useApp } from '../state/AppContext';
import { appReducer } from '../state/appReducer';
import { useSessionManager } from './useSessionManager';
import { createSessionRuntimeSnapshot } from './runtimeSnapshot';
import { findSessionStream, pendingStreamCacheKey } from './streamRegistry';

export function useStartNewTrip() {
  const { dispatch, activeStreamsRef, currentStateRef, sessionRuntimeCacheRef } = useApp();
  const { setLastSession } = useSessionManager();
  return useCallback(() => {
    const current = currentStateRef.current;
    const stream = findSessionStream(activeStreamsRef.current, current.currentSessionId, current.conversationEpoch);
    if (stream) {
      sessionRuntimeCacheRef.current.set(current.currentSessionId ?? pendingStreamCacheKey(stream.token), createSessionRuntimeSnapshot(current));
    }
    const clearAction = { type: 'CLEAR_CHAT' as const };
    // 在 React 提交下一帧之前，流事件也必须写入原会话的快照。
    currentStateRef.current = appReducer(current, clearAction);
    dispatch(clearAction);
    setLastSession(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('session_id');
    url.searchParams.delete('run_id');
    url.searchParams.set('view', 'chat');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'chat' });
  }, [activeStreamsRef, currentStateRef, dispatch, sessionRuntimeCacheRef, setLastSession]);
}
