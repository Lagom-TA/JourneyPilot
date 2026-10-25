import { type AppState } from "../state/state";
export type SessionRuntimeSnapshot = Pick<AppState, 'conversationEpoch' | 'currentSessionId' | 'currentTripRunId' | 'currentTripRunStatus' | 'currentTripRunRecovery' | 'tripRunSource' | 'tripRunRefreshKey' | 'currentMessages' | 'historyPaging' | 'thinkingSteps' | 'deliveryBundle' | 'deliveryBundleLoadState' | 'tripSummaryCard' | 'planApprovalGate' | 'pendingGuidedIntake' | 'pendingRouteConfirmation' | 'lastRouteDecision' | 'controlledTripIdentity' | 'runCostLive' | 'runCostSummary' | 'isStreaming' | 'isSynthesizing' | 'canvasOpen' | 'canvasFullscreen' | 'mobileCanvasOpen' | 'inputMode'>;
export interface ActiveStreamHandle {
    token: string;
    sessionId: string | null;
    runId: string | null;
    controller: AbortController | null;
}
export function createSessionRuntimeSnapshot(state: AppState): SessionRuntimeSnapshot {
    return {
        conversationEpoch: state.conversationEpoch,
        currentSessionId: state.currentSessionId,
        currentTripRunId: state.currentTripRunId,
        currentTripRunStatus: state.currentTripRunStatus,
        currentTripRunRecovery: state.currentTripRunRecovery,
        tripRunSource: state.tripRunSource,
        tripRunRefreshKey: state.tripRunRefreshKey,
        currentMessages: state.currentMessages,
        historyPaging: state.historyPaging,
        thinkingSteps: state.thinkingSteps,
        deliveryBundle: state.deliveryBundle,
        deliveryBundleLoadState: state.deliveryBundleLoadState,
        tripSummaryCard: state.tripSummaryCard,
        planApprovalGate: state.planApprovalGate,
        pendingGuidedIntake: state.pendingGuidedIntake,
        pendingRouteConfirmation: state.pendingRouteConfirmation,
        lastRouteDecision: state.lastRouteDecision,
        controlledTripIdentity: state.controlledTripIdentity,
        runCostLive: state.runCostLive,
        runCostSummary: state.runCostSummary,
        isStreaming: state.isStreaming,
        isSynthesizing: state.isSynthesizing,
        canvasOpen: state.canvasOpen,
        canvasFullscreen: state.canvasFullscreen,
        mobileCanvasOpen: state.mobileCanvasOpen,
        inputMode: state.inputMode,
    };
}
