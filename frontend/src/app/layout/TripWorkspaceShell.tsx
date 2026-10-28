import { AnimatePresence } from 'motion/react';
import { getCurrentDeliveryBundle } from '../../features/travel/api/delivery';
import { PresenceFrame } from '../../components/ui/PresenceSurface';
import { useApp } from '../state/AppContext';
import { useCurrentBundleWeatherRefresh } from '../session/useCurrentBundleWeatherRefresh';
import { isPublicDeliveryBundle } from '../../features/travel/types/delivery';
import { ConversationThread } from '../../features/chat/components/ConversationThread';
import { DeliveryWorkspace } from '../../features/travel/components/workspace/DeliveryWorkspace';
import { emphasisEnter, slideUp } from '../../lib/motion';
import React from 'react';

export const TripWorkspaceShell: React.FC = () => {
  const { state, dispatch, currentStateRef } = useApp();
  const retryCurrentBundle = React.useCallback(async () => {
    const runId = state.currentTripRunId;
    if (!runId) return;
    dispatch({ type: 'SET_DELIVERY_BUNDLE_LOAD_STATE', payload: { status: 'loading', message: null } });
    try {
      const bundle = await getCurrentDeliveryBundle(runId, state.currentSessionId);
      if (!isPublicDeliveryBundle(bundle) || bundle.manifest.run_id !== runId) {
        throw new Error('delivery bundle contract mismatch');
      }
      if (currentStateRef.current.currentTripRunId !== runId) return;
      dispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: bundle });
    } catch {
      if (currentStateRef.current.currentTripRunId !== runId) return;
      dispatch({
        type: 'SET_DELIVERY_BUNDLE_LOAD_STATE',
        payload: { status: 'error', message: '暂时无法加载这趟旅行的正式结果，请稍后重试。' },
      });
    }
  }, [currentStateRef, dispatch, state.currentSessionId, state.currentTripRunId]);

  const hasJourneyWorkspace = state.deliveryBundle !== null
    || Boolean(state.currentTripRunId && state.controlledTripIdentity);
  useCurrentBundleWeatherRefresh(state.deliveryBundle !== null && state.deliverableView !== 'full_report');

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-bg">
      {(state.deliveryBundleLoadState.status === 'error' || state.deliveryBundleLoadState.status === 'loading') && (
        <div className="flex-none px-3 pt-3 sm:px-4">
          <div role="alert" className="mx-auto flex max-w-3xl items-center justify-between gap-3 rounded-card border border-stroke bg-panel px-4 py-3 text-sm text-ink shadow-sm">
            <span className="min-w-0 break-words">
              {state.deliveryBundleLoadState.status === 'loading' ? '正在重新加载这趟旅行…' : state.deliveryBundleLoadState.message}
            </span>
            <button
              type="button"
              onClick={() => void retryCurrentBundle()}
              disabled={state.deliveryBundleLoadState.status === 'loading'}
              className="min-h-9 shrink-0 rounded-label border border-stroke bg-surface px-3 text-xs font-semibold text-ink hover:bg-accent-soft disabled:opacity-60"
            >重试</button>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1" data-testid="trip-workspace-layout">
        <AnimatePresence mode="popLayout" initial={false}>
          {hasJourneyWorkspace ? (
            <PresenceFrame key="journey-workspace" className="h-full min-h-0 w-full" variants={emphasisEnter} initial="hidden" animate="visible" exit="exit">
              <DeliveryWorkspace bundle={state.deliveryBundle} />
            </PresenceFrame>
          ) : (
            <PresenceFrame key="workspace-conversation" className="h-full min-h-0 w-full" data-testid="workspace-conversation" variants={slideUp} initial="hidden" animate="visible" exit="exit">
              <ConversationThread />
            </PresenceFrame>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};
