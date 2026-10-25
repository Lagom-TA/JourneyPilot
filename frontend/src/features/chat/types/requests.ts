import { type JourneyRoute, type RouteDecision, type ControlledTripIdentity, type GuidedIntakeState, type PlanGateDecisionAction } from "../../travel/types/planner";
export interface ChatRequest {
    messages: Array<{
        role: string;
        content: string;
        message_id?: string;
        type?: string;
    }>;
    session_id?: string | null;
    run_id?: string | null;
    route?: JourneyRoute | null;
    route_decision?: RouteDecision | null;
    controlled_trip_identity?: ControlledTripIdentity | null;
    guided_intake?: GuidedIntakeState | null;
    preset_id?: string | null;
    selected_mcp_servers?: string[];
    plan_gate?: boolean | null;
    gate_decision?: {
        action: PlanGateDecisionAction;
        content?: string;
    } | null;
}
