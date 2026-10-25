export type ChatErrorAction = 'retry' | 'reload' | 'edit' | null;
export type ChatErrorKind = 'fault' | 'guard_blocked';
export interface ChatErrorGuidance {
    title: string;
    description: string;
    action: ChatErrorAction;
    actionLabel?: string;
}
function normalizedError(raw: string): string {
    return raw
        .replace(/^请求失败\s*[:：]\s*/i, '')
        .replace(/^error\s*[:：]\s*/i, '')
        .trim();
}
export function getChatErrorGuidance(raw: string, kind: ChatErrorKind): ChatErrorGuidance {
    if (kind === 'guard_blocked') {
        return {
            title: '这个请求被安全策略拒绝',
            description: '重新发送同样的内容仍会被拒绝。换一个旅行规划相关的问题即可继续。',
            action: null,
        };
    }
    const message = normalizedError(raw);
    if (/\b(404|405)\b|not found|method not allowed/i.test(message)) {
        return {
            title: '旅行助手没有正确连接',
            description: '请重新启动 JourneyPilot，等待服务就绪后刷新这个页面。直接重新发送不会解决这个问题。',
            action: 'reload',
            actionLabel: '刷新页面',
        };
    }
    if (/\b(401|403)\b|unauthorized|forbidden|api[ _-]?key|authentication/i.test(message)) {
        return {
            title: '旅行助手暂时不可用',
            description: '请稍后重试；如果问题持续出现，请刷新页面后重新开始。',
            action: 'reload',
            actionLabel: '刷新页面',
        };
    }
    if (/\b(400|422)\b|消息内容不能为空|validation error|invalid request/i.test(message)) {
        return {
            title: '还需要调整一下行程需求',
            description: '请补充或修改目的地、出发时间、天数等信息后重新发送。',
            action: 'edit',
            actionLabel: '修改需求',
        };
    }
    if (/\b429\b|too many requests|rate limit/i.test(message)) {
        return {
            title: '现在请求有点多',
            description: '你的行程需求已经保留，稍等片刻后再试一次。',
            action: 'retry',
            actionLabel: '再试一次',
        };
    }
    if (/无法连接|failed to fetch|networkerror|network error|load failed|connection refused/i.test(message)) {
        return {
            title: '暂时连不上旅行助手',
            description: '请确认网络连接和 JourneyPilot 服务正常，稍等片刻后再试。',
            action: 'retry',
            actionLabel: '再试一次',
        };
    }
    if (/timeout|timed out|超时/i.test(message)) {
        return {
            title: '这次规划花的时间有点久',
            description: '可以再试一次；如果仍然超时，先缩短行程天数或减少同时查询的内容。',
            action: 'retry',
            actionLabel: '再试一次',
        };
    }
    if (/bundle_contract_superseded/i.test(message)) {
        return {
            title: '这趟旅行的结果无法展示',
            description: '它是用旧版本的结果格式保存的，现在已经读不出来了。请重新规划这趟旅行；重新载入不会有帮助。',
            action: null,
        };
    }
    if (/delivery_integrity_projection_failure/i.test(message)) {
        return {
            title: '这次运行的结果无法展示',
            description: '这趟旅行的结果没能生成可以展示的方案，继续这次运行会得到同一个结果。请重新规划这趟旅行。',
            action: null,
        };
    }
    if (/\b409\b|conflict|revision[ _-]?conflict|out[ _-]?of[ _-]?date/i.test(message)) {
        return {
            title: '这次旅行结果刚刚更新过',
            description: '服务端已经有更新的一版行程，为了不覆盖它，这次操作没有执行。请查看当前的行程结果；如果这次修改仍然需要，请在最新结果上重新发起。',
            action: null,
        };
    }
    if (/delivery[ _-]?integrity|delivery bundle|bundle (?:schema|revision|persistence)|atomic (?:save|persist|finaliz)/i.test(message)) {
        return {
            title: '旅行结果需要重新加载',
            description: '当前旅行结果未能安全保存。请刷新页面后重新载入；你的需求不会因此丢失。',
            action: 'reload',
            actionLabel: '重新加载',
        };
    }
    if (/\b5\d{2}\b|internal server error|bad gateway|service unavailable/i.test(message)) {
        return {
            title: '旅行助手暂时不可用',
            description: '你的需求已经保留，稍等片刻后可以再试一次。',
            action: 'retry',
            actionLabel: '再试一次',
        };
    }
    return {
        title: '暂时无法继续这次旅行',
        description: '可以再试一次；如果连续出现，请刷新页面后重新开始。',
        action: 'retry',
        actionLabel: '再试一次',
    };
}
export function cleanChatErrorDetail(raw: string): string {
    return normalizedError(raw) || 'Unknown error';
}
