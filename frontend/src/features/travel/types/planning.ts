import { type PlanGateDecisionAction } from "./planner";
export interface TripSummaryFact {
    label: string;
    value: string;
    state: 'confirmed' | 'default' | 'deferred';
}
export interface TripSummaryCard {
    headline: string;
    summary: string;
    facts: TripSummaryFact[];
    priorities: string[];
    currentFocus: string;
    nextMilestone: string | null;
    compactLine: string;
    requiresUserConfirmation: boolean;
}
export interface PlanGateStep {
    step: number;
    agents: string[];
    tasks?: Record<string, string>;
}
export interface PlanGateRequirement {
    requirementId: string;
    summary: string;
}
export interface PlanGateRecognizedRequirements {
    hard: PlanGateRequirement[];
    preferences: PlanGateRequirement[];
    attention: PlanGateRequirement[];
}
export interface PlanApprovalGate {
    gate: string;
    runId: string;
    status: 'pending' | 'cancelled';
    revision: number;
    revisionLimit: number;
    revisionLimitReached: boolean;
    steps: PlanGateStep[];
    planText: string;
    decisionOptions: PlanGateDecisionAction[];
    recognizedRequirements: PlanGateRecognizedRequirements;
}
