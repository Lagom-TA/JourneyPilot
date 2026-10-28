import { type AppState, type AppAction } from "./state";
import { canConfirmDeliveryBundle } from "../../features/travel/model/bundleAcceptance";
import { writeStoredActivePreset } from "../../features/presets/model/activePresetStorage";
import { chatReducer } from "../../features/chat/model/reducer";
import { travelReducer } from "../../features/travel/model/reducer";
export function appReducer(state: AppState, action: AppAction): AppState {
    switch (action.type) {
        case 'SET_ACTIVE_VIEW':
            return {
                ...state,
                activeView: action.payload,
            };
        case 'SET_SIDEBAR_COLLAPSED':
            return { ...state, sidebarCollapsed: action.payload };
        case 'SET_SESSION_ID':
            return { ...state, currentSessionId: action.payload };
        case 'SET_CURRENT_TRIP_RUN': {
            const isDifferentRun = action.payload.runId !== state.currentTripRunId;
            return {
                ...state,
                currentTripRunId: action.payload.runId,
                currentTripRunStatus: action.payload.status !== undefined
                    ? action.payload.status
                    : (isDifferentRun ? null : state.currentTripRunStatus),
                currentTripRunRecovery: isDifferentRun ? null : state.currentTripRunRecovery,
                currentTripRunReadOnly: action.payload.readOnly ?? (isDifferentRun ? false : state.currentTripRunReadOnly),
                tripRunSource: action.payload.source ?? (action.payload.runId ? state.tripRunSource : 'none'),
                tripSummaryCard: isDifferentRun ? null : state.tripSummaryCard,
                deliveryBundle: isDifferentRun ? null : state.deliveryBundle,
                deliveryBundleLoadState: isDifferentRun
                    ? { status: 'idle', message: null }
                    : state.deliveryBundleLoadState,
                deliverableView: isDifferentRun ? 'interactive_itinerary' : state.deliverableView,
            };
        }
        case 'SET_TRIP_RUN_STATUS': {
            const status = action.payload;
            const waitingAllowed = status === 'awaiting_input';
            const currentMessages = waitingAllowed
                ? state.currentMessages
                : state.currentMessages.map((message) => (message.type === 'waiting_approval'
                    ? { ...message, type: 'normal' as const, streamCompleted: true }
                    : message));
            return {
                ...state,
                currentTripRunStatus: status,
                currentTripRunRecovery: status === 'running' ? null : state.currentTripRunRecovery,
                currentMessages,
                planApprovalGate: waitingAllowed ? state.planApprovalGate : null,
                inputMode: 'normal',
            };
        }
        case 'CONFIRM_DELIVERY_BUNDLE':
            if (!canConfirmDeliveryBundle(state.deliveryBundle, action.payload))
                return state;
            return {
                ...state,
                currentTripRunId: action.payload.manifest.run_id,
                currentTripRunReadOnly: action.payload.manifest.run_id === state.currentTripRunId ? state.currentTripRunReadOnly : false,
                tripRunSource: 'live',
                deliveryBundle: action.payload,
                deliveryBundleLoadState: { status: 'ready', message: null },
                deliverableView: 'interactive_itinerary',
                sidebarCollapsed: true,
                canvasOpen: true,
                mobileCanvasOpen: false,
            };
        case 'RESTORE_SESSION_RUNTIME':
            return {
                ...state,
                ...action.payload,
                deliverableView: 'interactive_itinerary',
                conversationEpoch: state.conversationEpoch + 1,
            };
        case 'MARK_PENDING_DECISIONS_CANCELLED': {
            const messages = state.currentMessages.map((message) => (message.type === 'waiting_approval'
                ? { ...message, type: 'normal' as const, streamCompleted: true }
                : message));
            return {
                ...state,
                currentMessages: messages,
                planApprovalGate: state.planApprovalGate
                    ? { ...state.planApprovalGate, status: 'cancelled' }
                    : null,
                inputMode: 'normal',
            };
        }
        case 'CLEAR_TRACE':
            return { ...state, tripSummaryCard: null, planApprovalGate: null, runCostLive: null, runCostSummary: null };
        case 'SET_MOBILE_CANVAS_OPEN':
            return { ...state, mobileCanvasOpen: action.payload };
        case 'SET_ACTIVE_PRESET':
            writeStoredActivePreset(action.payload ? { id: action.payload.id, name: action.payload.name } : null);
            if (action.payload) {
                return { ...state, activePresetId: action.payload.id, activePresetName: action.payload.name };
            }
            return { ...state, activePresetId: null, activePresetName: null };
        case 'CLEAR_CHAT':
            return {
                ...state,
                conversationEpoch: state.conversationEpoch + 1,
                currentMessages: [],
                historyPaging: { nextBefore: null, hasMore: false, loading: false },
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
                currentSessionId: null,
                currentTripRunId: null,
                currentTripRunStatus: null,
                currentTripRunRecovery: null,
                currentTripRunReadOnly: false,
                tripRunSource: 'none',
                tripRunRefreshKey: state.tripRunRefreshKey + 1,
                canvasOpen: false,
                mobileCanvasOpen: false,
                inputMode: 'normal',
                isStreaming: false,
                isSynthesizing: false,
            };
        case 'SET_SESSIONS':
        case 'REMOVE_SESSION':
        case 'RENAME_SESSION':
        case 'SET_HISTORY_PAGING_LOADING':
        case 'PREPEND_HISTORY':
        case 'ADD_MESSAGE':
        case 'INSERT_MESSAGE_BEFORE_ID':
        case 'UPDATE_LAST_MESSAGE':
        case 'RESOLVE_WAITING_MESSAGES':
        case 'UPDATE_MESSAGE_BY_ID':
        case 'REMAP_MESSAGE_ID':
        case 'SET_THINKING_STEPS':
        case 'ADD_THINKING_STEP':
        case 'FINISH_LAST_THINKING_STEP':
        case 'UPDATE_LAST_TOOL_STEP':
        case 'USAGE_UPDATE':
        case 'SET_RUN_COST_SUMMARY':
        case 'SET_STREAMING':
        case 'SET_SYNTHESIZING':
        case 'SET_INPUT_MODE':
        case 'REMOVE_MESSAGE_BY_ID':
            return chatReducer(state, action);
        case 'SET_DELIVERY_BUNDLE_LOAD_STATE':
        case 'SET_DELIVERABLE_VIEW':
        case 'BUMP_TRIP_RUN_REFRESH':
        case 'SET_TRIP_SUMMARY_CARD':
        case 'SET_PLAN_APPROVAL_GATE':
        case 'SET_GUIDED_INTAKE':
        case 'SET_ROUTE_CONFIRMATION':
        case 'SET_LAST_ROUTE_DECISION':
        case 'SET_CONTROLLED_TRIP_IDENTITY':
            return travelReducer(state, action);
        default: return state;
    }
}
