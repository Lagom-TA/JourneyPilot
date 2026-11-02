import { type TripRunDetailResponse, type TripRunResponse } from "../../features/travel/types/runs";

export type SessionLoadFailure = 'run_detail_unavailable' | 'run_session_mismatch';

export interface SessionRunPlan {
    selectedRun: TripRunResponse | null;
    readOnly: boolean;
    failure: SessionLoadFailure | null;
}

/**
 * 决定一次会话恢复应该选中哪个 Trip Run。
 *
 * 请求了历史 Run 但没有拿到它的详情时，不能回退到最新 Run：那会让地址栏里的
 * run_id 与页面内容不一致。此时返回 failure，让调用方进入显式错误态。
 */
export function planRequestedRun(input: {
    sessionId: string;
    requestedRunId?: string;
    latestRun: TripRunResponse | null;
    requestedRunDetail: TripRunDetailResponse | null;
    requestedRunDetailFailed: boolean;
}): SessionRunPlan {
    if (!input.requestedRunId) {
        return { selectedRun: input.latestRun, readOnly: false, failure: null };
    }
    if (input.latestRun?.run_id === input.requestedRunId) {
        return { selectedRun: input.latestRun, readOnly: false, failure: null };
    }
    if (input.requestedRunDetailFailed || !input.requestedRunDetail) {
        return { selectedRun: null, readOnly: true, failure: 'run_detail_unavailable' };
    }
    if (input.requestedRunDetail.run.session_id !== input.sessionId) {
        return { selectedRun: null, readOnly: true, failure: 'run_session_mismatch' };
    }
    return { selectedRun: input.requestedRunDetail.run, readOnly: true, failure: null };
}

export function sessionLoadFailureMessage(failure: SessionLoadFailure | null): string {
    if (failure === 'run_session_mismatch') {
        return '这次生成记录不属于当前会话，暂时无法打开。';
    }
    return '暂时无法打开这次生成记录，请重试。';
}
