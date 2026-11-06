import { useCallback, useState } from "react";
import { useApp } from "../state/AppContext";
import { useSendMessage } from "./useSendMessage";

export const RESUME_TEXT = '继续上次被中断的规划';

/** 从最近的检查点继续当前被中断的 Run；生成面板与已交付行程的调整对话共用。 */
export function useResumeRun(runId: string | null) {
    const { state } = useApp();
    const { sendMessage } = useSendMessage();
    const [resuming, setResuming] = useState(false);
    const resume = useCallback(async () => {
        if (resuming || state.isStreaming) return;
        setResuming(true);
        try {
            await sendMessage(RESUME_TEXT, {
                resumeRunId: runId,
                route: 'trip_refinement',
                assistantPendingLabel: '正在从最近的位置继续',
            });
        }
        finally {
            setResuming(false);
        }
    }, [resuming, state.isStreaming, sendMessage, runId]);
    return { resume, resuming };
}
