import { getCurrentDeliveryBundle } from "../../features/travel/api/delivery";
import { m } from "motion/react";
import { Map as MapIcon } from "lucide-react";
import { useApp } from "../state/AppContext";
import { useIsMobileViewport } from "../../hooks/useMediaQuery";
import { useCurrentBundleWeatherRefresh } from "../session/useCurrentBundleWeatherRefresh";
import { cn } from "../../lib/utils";
import { attentionPulse, emphasisEnter } from "../../lib/motion";
import { isPublicDeliveryBundle } from "../../features/travel/types/delivery";
import { Sheet } from "../../components/ui/Sheet";
import { ConversationThread } from "../../features/chat/components/ConversationThread";
import { DeliveryWorkspace } from "../../features/travel/components/workspace/DeliveryWorkspace";
import { Neatline } from "../../components/ui/Neatline";
import React from 'react';
export const TripWorkspaceShell: React.FC = () => {
    const { state, dispatch, currentStateRef } = useApp();
    const isMobile = useIsMobileViewport();
    const retryCurrentBundle = React.useCallback(async () => {
        const runId = state.currentTripRunId;
        if (!runId)
            return;
        dispatch({
            type: 'SET_DELIVERY_BUNDLE_LOAD_STATE',
            payload: { status: 'loading', message: null },
        });
        try {
            const bundle = await getCurrentDeliveryBundle(runId, state.currentSessionId);
            if (!isPublicDeliveryBundle(bundle) || bundle.manifest.run_id !== runId) {
                throw new Error('delivery bundle contract mismatch');
            }
            if (currentStateRef.current.currentTripRunId !== runId)
                return;
            dispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: bundle });
        }
        catch {
            if (currentStateRef.current.currentTripRunId !== runId)
                return;
            dispatch({
                type: 'SET_DELIVERY_BUNDLE_LOAD_STATE',
                payload: {
                    status: 'error',
                    message: '暂时无法加载这趟旅行的正式结果，请稍后重试。',
                },
            });
        }
    }, [currentStateRef, dispatch, state.currentSessionId, state.currentTripRunId]);
    const hasCanvasWork = state.deliveryBundle !== null;
    const showCanvas = state.canvasOpen && hasCanvasWork;
    const fullscreen = showCanvas && state.canvasFullscreen;
    const canvasRevealedRef = React.useRef(false);
    React.useEffect(() => {
        if (showCanvas)
            canvasRevealedRef.current = true;
    }, [showCanvas]);
    const firstCanvasReveal = showCanvas && !canvasRevealedRef.current;
    useCurrentBundleWeatherRefresh(showCanvas && state.deliverableView === 'interactive_itinerary');
    return (<div className="flex h-full flex-col overflow-hidden bg-bg">
      {(state.deliveryBundleLoadState.status === 'error' || state.deliveryBundleLoadState.status === 'loading') && (<div className="flex-none px-3 pt-3 sm:px-4">
          <div role="alert" className="mx-auto flex max-w-3xl items-center justify-between gap-3 rounded-card border border-error/25 bg-panel px-4 py-3 text-sm text-ink shadow-sm">
            <span className="min-w-0 break-words">
              {state.deliveryBundleLoadState.status === 'loading'
                ? '正在重新加载这趟旅行…'
                : state.deliveryBundleLoadState.message}
            </span>
            <button type="button" onClick={() => void retryCurrentBundle()} disabled={state.deliveryBundleLoadState.status === 'loading'} className="shrink-0 rounded-card border border-stroke bg-surface px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-accent-soft disabled:cursor-wait disabled:opacity-60">
              重试
            </button>
          </div>
        </div>)}


      <div data-testid="trip-workspace-layout" className={cn('min-h-0 flex-1', showCanvas && 'gap-3 p-3 sm:p-4', showCanvas && !fullscreen
            ? 'flex lg:grid lg:grid-cols-[minmax(0,4.5fr)_minmax(0,5.5fr)]'
            : 'flex')}>


        <div data-testid="workspace-conversation" className={cn('relative flex min-h-0 min-w-0 flex-col overflow-hidden', showCanvas
            ? fullscreen
                ? 'flex-1 bg-panel shadow-sm lg:hidden'
                : 'flex-1 bg-panel shadow-sm'
            : 'w-full flex-1')}>
          {showCanvas && <Neatline />}
          <CanvasPill />
          <ConversationThread />
        </div>


        {showCanvas && !isMobile && (<m.div data-testid="workspace-canvas" className={cn('min-h-0 min-w-0', fullscreen && 'flex-1')} variants={emphasisEnter} initial={firstCanvasReveal ? 'hidden' : false} animate="visible">
            <DeliveryWorkspace bundle={state.deliveryBundle!}/>
          </m.div>)}
      </div>


      {isMobile && hasCanvasWork && (<Sheet open={state.mobileCanvasOpen} onClose={() => dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: false })} testId="canvas-sheet">
          <DeliveryWorkspace bundle={state.deliveryBundle!} variant="sheet"/>
        </Sheet>)}
    </div>);
};
const CanvasPill: React.FC = () => {
    const { state, dispatch } = useApp();
    const hasCanvasWork = state.deliveryBundle !== null;
    const isStreaming = state.isStreaming;
    const [pulse, setPulse] = React.useState(false);
    const prevHasCanvasWork = React.useRef(hasCanvasWork);
    React.useEffect(() => {
        if (!prevHasCanvasWork.current && hasCanvasWork && isStreaming)
            setPulse(true);
        prevHasCanvasWork.current = hasCanvasWork;
    }, [hasCanvasWork, isStreaming]);
    if (!hasCanvasWork)
        return null;
    return (<m.button type="button" data-testid="canvas-pill" onClick={() => dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: true })} animate={pulse ? attentionPulse : undefined} className={cn('absolute right-3 top-3 z-20 inline-flex items-center gap-1.5 rounded-full', 'border border-accent/25 bg-[var(--color-accent-soft)] px-3 py-1.5 text-xs font-semibold text-accent shadow-sm lg:hidden')}>
      <MapIcon size={12}/>
      <span className="max-w-[9em] truncate">查看行程</span>
    </m.button>);
};
