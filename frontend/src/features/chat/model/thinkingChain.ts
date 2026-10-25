import { type ThinkingStep } from "../types/messages";
export function shouldShowLiveDuration(step: ThinkingStep, isActiveContext: boolean): boolean {
    return Boolean(isActiveContext && step.toolStatus === 'running');
}
