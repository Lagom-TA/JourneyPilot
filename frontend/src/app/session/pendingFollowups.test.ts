import { describe, expect, it } from 'vitest';
import { formatPendingFollowups } from './pendingFollowups';

describe('待发送消息', () => {
    it('按顺序合并为一条下一轮输入', () => {
        expect(formatPendingFollowups([
            { id: 'a', text: '第一条', status: 'ready' },
            { id: 'b', text: '第二条', status: 'ready' },
            { id: 'c', text: '第三条', status: 'ready' },
        ])).toBe('1. 第一条\n\n2. 第二条\n\n3. 第三条');
    });
});
