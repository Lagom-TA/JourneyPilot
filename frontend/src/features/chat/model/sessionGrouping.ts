import { type ChatSession } from "../types/messages";
export function groupByDate(sessions: ChatSession[]): Map<string, ChatSession[]> {
    const groups = new Map<string, ChatSession[]>();
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
    const startOfWeek = startOfToday - 6 * 24 * 60 * 60 * 1000;
    const sorted = [...sessions].sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime());
    for (const session of sorted) {
        const t = session.updatedAt.getTime();
        let label: string;
        if (t >= startOfToday)
            label = '今天';
        else if (t >= startOfYesterday)
            label = '昨天';
        else if (t >= startOfWeek)
            label = '近 7 天';
        else
            label = '更早';
        const list = groups.get(label);
        if (list)
            list.push(session);
        else
            groups.set(label, [session]);
    }
    return groups;
}
