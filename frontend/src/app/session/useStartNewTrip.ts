import { useCallback } from 'react';
import { useApp } from '../state/AppContext';
import { useSessionManager } from './useSessionManager';
import { abortSessionStream } from './streamRegistry';

export function useStartNewTrip() {
  const { state, dispatch, activeStreamsRef } = useApp();
  const { setLastSession } = useSessionManager();
  return useCallback(() => {
    abortSessionStream(activeStreamsRef.current, state);
    dispatch({ type: 'CLEAR_CHAT' });
    setLastSession(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('session_id');
    url.searchParams.delete('run_id');
    url.searchParams.set('view', 'chat');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'chat' });
  }, [activeStreamsRef, dispatch, setLastSession, state]);
}
