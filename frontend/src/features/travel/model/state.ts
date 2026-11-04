import { type TripRunStatus, type TripRunRecovery } from "../types/runs";
import { type PublicDeliveryBundle } from "../types/delivery";
import { type TripSummaryCard, type PlanApprovalGate } from "../types/planning";
import { type RouteDecision, type ControlledTripIdentity, type UnderstandingQuestion } from "../types/planner";
export interface TravelState {
    currentTripRunId: string | null;
    currentTripRunStatus: TripRunStatus | null;
    currentTripRunRecovery: TripRunRecovery | null;
    currentTripRunReadOnly: boolean;
    tripRunSource: 'none' | 'live';
    tripRunRefreshKey: number;
    deliveryBundle: PublicDeliveryBundle | null;
    deliveryBundleLoadState: {
        status: 'idle' | 'loading' | 'ready' | 'error';
        message: string | null;
    };
    deliverableView: 'interactive_itinerary' | 'full_report' | 'today';
    tripSummaryCard: TripSummaryCard | null;
    planApprovalGate: PlanApprovalGate | null;
    /** 理解阶段当前等待回答的问题；runId 绑定所属 Run。 */
    understandingQuestions: {
        runId: string;
        revision: number;
        approvalToken: string;
        questions: UnderstandingQuestion[];
        retryLocation: boolean;
        retryResearch?: boolean;
        message?: string;
    } | null;
    /** 提交旅行想法后即进入工作台；首页只服务尚未开始的新会话。 */
    workspaceActive: boolean;
    pendingRouteConfirmation: {
        rawInput: string;
        decision: RouteDecision;
    } | null;
    lastRouteDecision: RouteDecision | null;
    controlledTripIdentity: ControlledTripIdentity | null;
}
export type TravelAction = {
    type: 'SET_TRIP_RUN_RECOVERY';
    payload: TripRunRecovery | null;
} | {
    type: 'SET_DELIVERY_BUNDLE_LOAD_STATE';
    payload: TravelState['deliveryBundleLoadState'];
} | {
    type: 'SET_DELIVERABLE_VIEW';
    payload: TravelState['deliverableView'];
} | {
    type: 'BUMP_TRIP_RUN_REFRESH';
} | {
    type: 'SET_TRIP_SUMMARY_CARD';
    payload: TripSummaryCard | null;
} | {
    type: 'SET_PLAN_APPROVAL_GATE';
    payload: PlanApprovalGate | null;
} | {
    type: 'SET_UNDERSTANDING_QUESTIONS';
    payload: TravelState['understandingQuestions'];
} | {
    type: 'ENTER_WORKSPACE';
} | {
    type: 'SET_ROUTE_CONFIRMATION';
    payload: {
        rawInput: string;
        decision: RouteDecision;
    } | null;
} | {
    type: 'SET_LAST_ROUTE_DECISION';
    payload: RouteDecision | null;
} | {
    type: 'SET_CONTROLLED_TRIP_IDENTITY';
    payload: ControlledTripIdentity | null;
};
