import { type ActiveView, isActiveView, type AppState } from "./state";
import { readStoredActivePreset } from "../../features/presets/model/activePresetStorage";
function getInitialActiveView(): ActiveView {
    if (typeof window === 'undefined')
        return 'chat';
    const v = new URLSearchParams(window.location.search).get('view');
    return isActiveView(v) ? v : 'chat';
}
export const initialState: AppState = {
    activeView: getInitialActiveView(),
    sidebarCollapsed: typeof window !== 'undefined' && window.innerWidth < 1024,
    historyPaging: { nextBefore: null, hasMore: false, loading: false },
    currentSessionId: null,
    conversationEpoch: 0,
    currentTripRunId: null,
    currentTripRunStatus: null,
    currentTripRunRecovery: null,
    tripRunSource: 'none',
    tripRunRefreshKey: 0,
    sessions: [],
    currentMessages: [],
    thinkingSteps: [],
    deliveryBundle: null,
    deliveryBundleLoadState: { status: 'idle', message: null },
    deliverableView: 'interactive_itinerary',
    tripSummaryCard: null,
    planApprovalGate: null,
    pendingGuidedIntake: null,
    pendingRouteConfirmation: null,
    lastRouteDecision: null,
    controlledTripIdentity: null,
    runCostLive: null,
    runCostSummary: null,
    isStreaming: false,
    isSynthesizing: false,
    canvasOpen: false,
    canvasFullscreen: false,
    mobileCanvasOpen: false,
    inputMode: 'normal',
    ...(() => {
        const stored = readStoredActivePreset();
        return {
            activePresetId: stored?.id ?? null,
            activePresetName: stored?.name ?? null,
        };
    })(),
    boardingPassFlash: 0,
};
