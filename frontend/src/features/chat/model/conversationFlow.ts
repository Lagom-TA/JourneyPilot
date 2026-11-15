import { type Message } from "../types/messages";
export const RESEARCH_START_TEXT = '开始调研';
export function messageText(message?: Pick<Message, 'displayContent' | 'content'> | null): string {
    return (message?.displayContent || message?.content || '').trim();
}
const DELIVERY_READY_TEXT = '旅行方案已保存，可以查看完整行程。';
export function hideDeliveryReadyNotice(message: Message): Message {
    if (message.role !== 'assistant' || (message.type && message.type !== 'normal') || messageText(message) !== DELIVERY_READY_TEXT
        || (message.content.trim() && message.content.trim() !== DELIVERY_READY_TEXT))
        return message;
    return { ...message, content: '', displayContent: '' };
}
export function isResearchStartMessage(message: Message): boolean {
    return message.role === 'user' && messageText(message) === RESEARCH_START_TEXT;
}
export function researchStartIndex(messages: Message[]): number {
    return messages.findIndex(isResearchStartMessage);
}
export function hasResearchStarted(messages: Message[]): boolean {
    return researchStartIndex(messages) >= 0;
}
function afterSetupBoundary(messages: Message[], boundary: number): Message[] {
    const retainedEvents = messages
        .slice(0, boundary + 1)
        .filter((message) => message.type === 'context_compaction');
    return [...retainedEvents, ...messages.slice(boundary + 1)];
}
export function projectVisibleMessages(messages: Message[], options?: {
    planGatePending?: boolean;
}): Message[] {
    const firstCurrent = messages.findIndex((message) => !message.isEarlierHistory);
    if (firstCurrent > 0) {
        return [
            ...messages.slice(0, firstCurrent),
            ...projectVisibleMessages(messages.slice(firstCurrent), options),
        ];
    }
    const startIndex = researchStartIndex(messages);
    if (startIndex >= 0)
        return afterSetupBoundary(messages, startIndex);
    if (options?.planGatePending) {
        for (let index = messages.length - 1; index >= 0; index -= 1) {
            if (messages[index].role === 'user')
                return afterSetupBoundary(messages, index);
        }
    }
    return messages;
}
