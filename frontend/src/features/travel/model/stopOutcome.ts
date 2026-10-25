import { apiErrorDetail, apiErrorDetailString } from "../../../lib/apiErrorDetail";
import { isTripRunStatus, type TripRunStatus } from "../types/runs";
export interface StopOutcome {
    stopped: boolean;
    status: TripRunStatus | null;
    message: string | null;
}
export function stopOutcomeFromError(error: unknown): StopOutcome {
    const detail = apiErrorDetail(error);
    if (detail.code === 'run_not_cancellable') {
        const reported = apiErrorDetailString(error, 'status');
        const status = isTripRunStatus(reported) ? reported : null;
        return {
            stopped: true,
            status,
            message: status === 'cancelled' ? null : '这次运行已经结束了，不需要再停止。',
        };
    }
    return {
        stopped: false,
        status: null,
        message: '这个页面已经停止接收结果，但规划可能仍在继续。稍后回到这趟旅行看它的状态。',
    };
}
