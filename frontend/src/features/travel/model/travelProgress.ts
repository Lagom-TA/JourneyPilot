import { type ThinkingStep } from "../../chat/types/messages";
import { deriveStages } from "../../chat/model/agentStages";
export function derivePlanningStageSnapshot(args: {
    steps: ThinkingStep[];
    isStreaming: boolean;
    isSynthesizing: boolean;
    answerStarted: boolean;
    completed: boolean;
}) {
    return deriveStages(args.steps, args);
}
