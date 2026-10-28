import { type TripRunStatus, type TripRunRecovery } from "../types/runs";
import { type PublicDeliveryBundle } from "../types/delivery";
import { type TripSummaryCard, type PlanApprovalGate } from "../types/planning";
import { type GuidedIntakeState, type RouteDecision, type ControlledTripIdentity } from "../types/planner";
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
    pendingGuidedIntake: GuidedIntakeState | null;
    pendingRouteConfirmation: {
        rawInput: string;
        decision: RouteDecision;
    } | null;
    lastRouteDecision: RouteDecision | null;
    controlledTripIdentity: ControlledTripIdentity | null;
}
export type TravelAction = {
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
    type: 'SET_GUIDED_INTAKE';
    payload: GuidedIntakeState | null;
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
