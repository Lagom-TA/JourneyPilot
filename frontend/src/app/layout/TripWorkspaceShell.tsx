import { AnimatePresence, useReducedMotion } from 'motion/react';
import type { Variants } from 'motion/react';
import { getCurrentDeliveryBundle } from '../../features/travel/api/delivery';
import { PresenceFrame } from '../../components/ui/PresenceSurface';
import { useApp } from '../state/AppContext';
import { useCurrentBundleWeatherRefresh } from '../session/useCurrentBundleWeatherRefresh';
import { isPublicDeliveryBundle } from '../../features/travel/types/delivery';
import { ConversationThread } from '../../features/chat/components/ConversationThread';
import { PageSkeleton } from '../components/PageSkeleton';
import { DeliveryWorkspace } from '../../features/travel/components/workspace/DeliveryWorkspace';
import { emphasisEnter, slideUp } from '../../lib/motion';
import React from 'react';

const directHandoff: Variants = {
  hidden: { opacity: 1 },
  visible: { opacity: 1, transition: { duration: 0 } },
  exit: { opacity: 1, transition: { duration: 0 } },
};

export const TripWorkspaceShell: React.FC = () => {
  const { state, dispatch, currentStateRef } = useApp();
  const reducedMotion = useReducedMotion();
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

  // 提交旅行想法即进入工作台；工作台内部自行区分等待、生成与交付形态。
  const hasJourneyWorkspace = state.workspaceActive
    || state.deliveryBundle !== null
    || state.currentTripRunId !== null;
  const previousJourneyWorkspaceRef = React.useRef(hasJourneyWorkspace);
  const handoffFocusPendingRef = React.useRef(false);
  React.useEffect(() => {
    const previous = previousJourneyWorkspaceRef.current;
    previousJourneyWorkspaceRef.current = hasJourneyWorkspace;
    if (previous !== hasJourneyWorkspace) handoffFocusPendingRef.current = hasJourneyWorkspace;
  }, [hasJourneyWorkspace]);
  const focusJourneyWorkspace = React.useCallback(() => {
    if (!handoffFocusPendingRef.current) return;
    handoffFocusPendingRef.current = false;
    document.querySelector<HTMLElement>('[data-workspace-handoff-focus]')?.focus({ preventScroll: true });
  }, []);
  useCurrentBundleWeatherRefresh(state.deliveryBundle !== null && state.deliverableView !== 'full_report');

  if (!state.sessionInitialized) return <PageSkeleton />;

  const deliveryBundleLoadState = state.deliveryBundleLoadState;
  const showRecoveryNotice = deliveryBundleLoadState.status === 'error' || deliveryBundleLoadState.status === 'loading';

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-bg">
      <div className="relative min-h-0 flex-1" data-testid="trip-workspace-layout">
        <AnimatePresence mode="popLayout" initial={false}>
          {hasJourneyWorkspace ? (
            <PresenceFrame
              key="journey-workspace"
              className="h-full min-h-0 w-full"
              data-testid="journey-workspace"
              variants={reducedMotion ? directHandoff : emphasisEnter}
              initial="hidden"
              animate="visible"
              exit="exit"
              onAnimationComplete={focusJourneyWorkspace}
            >
              <DeliveryWorkspace bundle={state.deliveryBundle} />
            </PresenceFrame>
          ) : (
            <PresenceFrame key="workspace-conversation" className="h-full min-h-0 w-full" data-testid="workspace-conversation" variants={reducedMotion ? directHandoff : slideUp} initial="hidden" animate="visible" exit="exit">
              <ConversationThread />
            </PresenceFrame>
          )}
        </AnimatePresence>
      </div>

      {/* 恢复提示只做状态提示：脱离文档流覆盖在工作区上方，不占高度、不抢焦点、不拦框外操作。 */}
      {showRecoveryNotice && (
        <div
          data-testid="delivery-recovery-notice"
          role="alert"
          aria-atomic="true"
          className="recovery-notice flex items-center justify-between gap-3 rounded-card border border-stroke bg-panel/95 px-4 py-2.5 text-sm text-ink shadow-lg backdrop-blur"
        >
          <span data-testid="delivery-recovery-notice-message" className="min-w-0 break-words">
            {deliveryBundleLoadState.status === 'loading' ? '正在重新加载这趟旅行…' : deliveryBundleLoadState.message}
          </span>
          <button
            type="button"
            onClick={() => void retryCurrentBundle()}
            disabled={deliveryBundleLoadState.status === 'loading'}
            className="min-h-9 shrink-0 rounded-label border border-stroke bg-surface px-3 text-xs font-semibold text-ink hover:bg-accent-soft disabled:opacity-60"
          >重试</button>
        </div>
      )}
    </div>
  );
};
