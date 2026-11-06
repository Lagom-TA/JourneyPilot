import { type OrbState } from "thinking-orbs";
export const ORB_LABELS: Record<OrbState, string> = {
    working: '正在处理',
    searching: '正在查找资料',
    solving: '正在核对与求解',
    listening: '正在理解你的需求',
    connecting: '正在衔接交通与任务',
    weaving: '正在编排行程',
    composing: '正在生成内容',
    breathing: '等待中',
    shaping: '正在整理完整计划',
};
