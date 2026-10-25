import { type TravelState, type TravelAction } from "./state";
export function travelReducer<T extends TravelState>(state: T, action: TravelAction): T {
    switch (action.type) {
        case 'SET_DELIVERY_BUNDLE_LOAD_STATE':
            return { ...state, deliveryBundleLoadState: action.payload };
        case 'SET_DELIVERABLE_VIEW':
            return { ...state, deliverableView: action.payload };
        case 'BUMP_TRIP_RUN_REFRESH':
            return { ...state, tripRunRefreshKey: state.tripRunRefreshKey + 1 };
        case 'SET_TRIP_SUMMARY_CARD':
            return { ...state, tripSummaryCard: action.payload };
        case 'SET_PLAN_APPROVAL_GATE':
            return { ...state, planApprovalGate: action.payload };
        case 'SET_GUIDED_INTAKE':
            return { ...state, pendingGuidedIntake: action.payload };
        case 'SET_ROUTE_CONFIRMATION':
            return { ...state, pendingRouteConfirmation: action.payload };
        case 'SET_LAST_ROUTE_DECISION':
            return { ...state, lastRouteDecision: action.payload };
        case 'SET_CONTROLLED_TRIP_IDENTITY':
            return { ...state, controlledTripIdentity: action.payload };
        default: return state;
    }
}
