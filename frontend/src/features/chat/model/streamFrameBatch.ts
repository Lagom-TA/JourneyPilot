import { type ChatAction } from "./state";
import { type Message } from "../types/messages";
import { type UsageUpdateEvent } from "../types/cost";
export function createStreamFrameBatch(scopedDispatch: (action: ChatAction) => void, assistantMessage: Message) {
    let frameId: number | null = null;
    const pendingUsage: UsageUpdateEvent[] = [];
    let assistantUpdateQueued = false;
    const flushFrame = () => {
        frameId = null;
        if (pendingUsage.length > 0) {
            const usageEvents = pendingUsage.splice(0);
            for (const usage of usageEvents) {
                scopedDispatch({ type: 'USAGE_UPDATE', payload: usage });
            }
        }
        if (assistantUpdateQueued) {
            assistantUpdateQueued = false;
            scopedDispatch({
                type: 'UPDATE_LAST_MESSAGE',
                payload: {
                    content: assistantMessage.content,
                    displayContent: assistantMessage.displayContent,
                },
            });
        }
    };
    const scheduleFrame = () => {
        if (typeof window === 'undefined') {
            flushFrame();
            return;
        }
        if (frameId == null) {
            frameId = window.requestAnimationFrame(flushFrame);
        }
    };
    const flushFrameNow = () => {
        if (frameId != null && typeof window !== 'undefined') {
            window.cancelAnimationFrame(frameId);
        }
        flushFrame();
    };
    return {
        flushFrameNow,
        queueUsage(usage: UsageUpdateEvent) { pendingUsage.push(usage); scheduleFrame(); },
        queueAssistantUpdate() { assistantUpdateQueued = true; scheduleFrame(); },
    };
}
export type StreamFrameBatch = ReturnType<typeof createStreamFrameBatch>;
