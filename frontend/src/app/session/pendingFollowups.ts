export interface PendingFollowup {
    id: string;
    text: string;
    status: 'waiting' | 'ready' | 'paused';
    editing?: boolean;
    messageId?: string;
}

export type PendingFollowups = Record<string, PendingFollowup[]>;

export function formatPendingFollowups(items: PendingFollowup[]): string {
    const texts = items.map(item => item.text.trim()).filter(Boolean);
    return texts.length < 2 ? texts[0] ?? '' : texts.map((text, index) => `${index + 1}. ${text}`).join('\n\n');
}
