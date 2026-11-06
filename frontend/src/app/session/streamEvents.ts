import { type AppState } from "../state/state";
import { normalizeTripSummaryCard } from "../../features/travel/model/tripSummaryCard";
import { normalizePlanApprovalGate } from "../../features/travel/model/planApprovalGate";
import { type Message } from "../../features/chat/types/messages";
import { type SSEEvent } from "../../features/chat/types/events";
import { isTripRunStatus } from "../../features/travel/types/runs";
import { type JourneyRoute, type PlanGateDecisionAction } from "../../features/travel/types/planner";
import { type MutableRefObject } from "react";
import { type StreamOwnership } from "./streamOwnership";
import { createStreamPresentation } from "../../features/chat/model/streamPresentation";
import { createDeliveryProtocol } from "../../features/travel/model/deliveryProtocol";
import { type StreamFrameBatch } from "../../features/chat/model/streamFrameBatch";
export function createStreamEvents(ownership: StreamOwnership, assistantMessage: Message, text: string, initialCurrentTripRunId: string | null, pendingLabel: string | undefined, currentStateRef: MutableRefObject<AppState>, setLastSession: (id: string | null) => void, frame: StreamFrameBatch, gateAction?: PlanGateDecisionAction) {
    const { identity, scopedDispatch, isStreamVisible, updateActiveStreamHandle } = ownership;
    const { flushFrameNow } = frame;
    let streamFailed = false;
    let responseCompleted = false;
    let waitingForRouteConfirmation = false;
    let waitingForRequiredInput = false;
    let planningRunId: string | null = null;
    let waitingForGateAcceptance = Boolean(gateAction);
    const presentation = createStreamPresentation(scopedDispatch, assistantMessage, pendingLabel, frame);
    const routeStatus = (route?: JourneyRoute) => ({
        destination_discovery: '正在推荐目的地',
        trip_planning: '正在整理旅行信息',
        fast_answer: '正在回答问题',
        trip_refinement: '正在调整行程',
    }[route || 'fast_answer']);
    const protocol = createDeliveryProtocol(identity, bundle => {
        flushFrameNow();
        scopedDispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: bundle });
    }, terminal => {
        responseCompleted = true;
        flushFrameNow();
        scopedDispatch({
            type: 'FINISH_LAST_THINKING_STEP',
            payload: { endTime: new Date(), tsMs: terminal.ts_ms },
        });
        if (!assistantMessage.content.trim()) {
            const readyMessage = '旅行方案已保存，可以查看完整行程。';
            assistantMessage.content = readyMessage;
            assistantMessage.displayContent = readyMessage;
        }
        scopedDispatch({
            type: 'UPDATE_LAST_MESSAGE',
            payload: {
                content: assistantMessage.content,
                displayContent: assistantMessage.displayContent,
                streamCompleted: true,
            },
        });
        if (terminal.run_cost_summary !== undefined) {
            scopedDispatch({ type: 'SET_RUN_COST_SUMMARY', payload: terminal.run_cost_summary });
        }
        scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'completed' });
        scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
        scopedDispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
        scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
    });
    return { protocol, get failed() { return streamFailed; }, get completed() { return responseCompleted; }, get awaitingInput() { return waitingForRequiredInput || waitingForRouteConfirmation; }, handleEvent(event: SSEEvent) {
            // chat_start 只说明流已打开；必须再收到工作流事件，才能确认中断的计划门真的恢复了。
            if (waitingForGateAcceptance && ['thinking', 'agent_progress', 'tool_start', 'work_explanation', 'trip_summary_card', 'chat_chunk'].includes(event.type)) {
                waitingForGateAcceptance = false;
                scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
                scopedDispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: null });
                scopedDispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
            }
            if (presentation.handle(event))
                return;
            switch (event.type) {
                case 'route_confirmation':
                    waitingForRouteConfirmation = true;
                    if (event.route_decision) {
                        scopedDispatch({ type: 'SET_LAST_ROUTE_DECISION', payload: event.route_decision });
                        scopedDispatch({ type: 'SET_ROUTE_CONFIRMATION', payload: { rawInput: text, decision: event.route_decision } });
                    }
                    scopedDispatch({ type: 'REMOVE_MESSAGE_BY_ID', payload: assistantMessage.id });
                    break;
                case 'chat_start':
                    if (event.route_decision) {
                        scopedDispatch({ type: 'SET_LAST_ROUTE_DECISION', payload: event.route_decision });
                        scopedDispatch({ type: 'SET_ROUTE_CONFIRMATION', payload: null });
                        scopedDispatch({ type: 'UPDATE_MESSAGE_BY_ID', payload: { id: assistantMessage.id, pendingStatusText: routeStatus(event.route_decision.route) } });
                    }
                    if (event.session_id) {
                        identity.sessionId = event.session_id;
                        updateActiveStreamHandle({ sessionId: event.session_id });
                        scopedDispatch({ type: 'SET_SESSION_ID', payload: event.session_id });
                        if (isStreamVisible())
                            setLastSession(event.session_id);
                    }
                    if (event.run_id) {
                        identity.runId = event.run_id;
                        updateActiveStreamHandle({ runId: event.run_id });
                        if (!waitingForGateAcceptance) {
                            scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
                            scopedDispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
                        }
                        if (event.route_decision?.route === 'trip_planning' || event.route_decision?.route === 'trip_refinement') {
                            planningRunId = event.run_id;
                            scopedDispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: null });
                            scopedDispatch({
                                type: 'SET_CURRENT_TRIP_RUN',
                                payload: {
                                    runId: event.run_id,
                                    source: 'live',
                                    status: 'running',
                                    preserveDelivery: event.route_decision?.route === 'trip_refinement',
                                },
                            });
                        }
                    }
                    if (event.message_id && event.message_id !== assistantMessage.id) {
                        // 续跑与已完成回答的重放都可能复用助手消息 ID。
                        // 先移除旧消息，避免重映射后出现两条相同 ID 的消息。
                        scopedDispatch({ type: 'REMOVE_MESSAGE_BY_ID', payload: event.message_id });
                        scopedDispatch({
                            type: 'REMAP_MESSAGE_ID',
                            payload: { fromId: assistantMessage.id, toId: event.message_id },
                        });
                        assistantMessage.id = event.message_id;
                    }
                    if (event.run_id) {
                        // 实时助手消息也要带上 Run 归属，恢复/切换 Run 时才不会
                        // 把当前正文和旧 Run 的消息混在一起。
                        scopedDispatch({
                            type: 'UPDATE_MESSAGE_BY_ID',
                            payload: { id: assistantMessage.id, runId: event.run_id },
                        });
                    }
                    break;
                case 'trip_identity_updated': {
                    if (event.run_id === identity.runId && event.controlled_trip_identity) {
                        scopedDispatch({ type: 'SET_CONTROLLED_TRIP_IDENTITY', payload: event.controlled_trip_identity });
                    }
                    break;
                }
                case 'trip_summary_card': {
                    const card = normalizeTripSummaryCard(event);
                    if (card)
                        scopedDispatch({ type: 'SET_TRIP_SUMMARY_CARD', payload: card });
                    break;
                }
                case 'understanding_questions': {
                    waitingForRequiredInput = true;
                    waitingForGateAcceptance = false;
                    flushFrameNow();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } });
                    const questions = Array.isArray(event.payload?.questions) ? event.payload.questions : [];
                    const retryLocation = Array.isArray(event.payload?.decision_options) && event.payload.decision_options.includes('retry');
                    if (event.run_id && (questions.length > 0 || retryLocation)) {
                        scopedDispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: {
                            runId: event.run_id,
                            revision: typeof event.payload?.revision === 'number' ? event.payload.revision : 0,
                            approvalToken: typeof event.payload?.approval_token === 'string' ? event.payload.approval_token : '',
                            questions,
                            retryLocation,
                            retryResearch: event.gate === 'research',
                            message: typeof event.payload?.message === 'string' ? event.payload.message : undefined,
                        } });
                        scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
                    }
                    if (isTripRunStatus(event.run_status)) {
                        scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: event.run_status });
                    }
                    scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
                    break;
                }
                case 'approval_gate_raised': {
                    waitingForRequiredInput = true;
                    waitingForGateAcceptance = false;
                    flushFrameNow();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } });
                    scopedDispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: null });
                    const gate = normalizePlanApprovalGate(event);
                    if (gate) {
                        scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: gate });
                        if (isTripRunStatus(event.run_status)) {
                            scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: event.run_status });
                        }
                    }
                    scopedDispatch({
                        type: 'UPDATE_LAST_MESSAGE',
                        payload: { type: 'waiting_approval' },
                    });
                    scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
                    break;
                }
                case 'delivery_ready': {
                    protocol.acceptDeliveryReady(event);
                    break;
                }
                case 'run_terminal': {
                    protocol.acceptDeliveryTerminal(event);
                    break;
                }
                case 'chat_complete': {
                    waitingForRequiredInput = waitingForRequiredInput || event.requires_input === true || event.run_status === 'awaiting_input';
                    responseCompleted = (!event.run_status || event.run_status === 'completed' || event.run_status === 'awaiting_input')
                        && !event.guard_blocked
                        && !waitingForRouteConfirmation;
                    flushFrameNow();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date(), tsMs: event.ts_ms } });
                    if (event.final_content && typeof event.final_content === 'string') {
                        assistantMessage.content = event.final_content;
                        assistantMessage.displayContent = event.final_content;
                        scopedDispatch({
                            type: 'UPDATE_LAST_MESSAGE',
                            payload: {
                                content: event.final_content,
                                displayContent: event.final_content,
                                streamCompleted: true,
                            },
                        });
                    }
                    else {
                        scopedDispatch({
                            type: 'UPDATE_LAST_MESSAGE',
                            payload: { streamCompleted: true },
                        });
                    }
                    if (event.run_id && (currentStateRef.current.currentTripRunId === event.run_id
                        || (!currentStateRef.current.currentTripRunId && !event.run_status && !initialCurrentTripRunId))) {
                        scopedDispatch({
                            type: 'SET_CURRENT_TRIP_RUN',
                            payload: {
                                runId: event.run_id,
                                source: 'live',
                                status: isTripRunStatus(event.run_status) ? event.run_status : undefined,
                            },
                        });
                    }
                    if (event.run_cost_summary !== undefined) {
                        scopedDispatch({ type: 'SET_RUN_COST_SUMMARY', payload: event.run_cost_summary });
                    }
                    if (event.run_status !== 'awaiting_input') {
                        scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
                        scopedDispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: null });
                        scopedDispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
                    }
                    if (isTripRunStatus(event.run_status)
                        && (!event.run_id || currentStateRef.current.currentTripRunId === event.run_id
                            || event.run_id === planningRunId)) {
                        scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: event.run_status });
                    }
                    if (event.guard_blocked) {
                        scopedDispatch({
                            type: 'UPDATE_LAST_MESSAGE',
                            payload: {
                                type: 'guard_blocked',
                                streamCompleted: true,
                                pendingStatusText: undefined,
                            },
                        });
                    }
                    break;
                }
                case 'run_cancelled': {
                    flushFrameNow();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } });
                    const hadPendingDecision = Boolean(currentStateRef.current.planApprovalGate
                        || currentStateRef.current.currentMessages.some((message) => message.type === 'waiting_approval'));
                    scopedDispatch({ type: 'MARK_PENDING_DECISIONS_CANCELLED' });
                    const finalContent = typeof event.final_content === 'string' && event.final_content.trim()
                        ? event.final_content
                        : '已取消当前规划。已产生的阶段性内容会保留在本次生成记录中。';
                    assistantMessage.content = finalContent;
                    assistantMessage.displayContent = finalContent;
                    if (hadPendingDecision) {
                        scopedDispatch({
                            type: 'ADD_MESSAGE',
                            payload: {
                                id: `${assistantMessage.id}-cancelled`,
                                role: 'assistant',
                                content: finalContent,
                                displayContent: finalContent,
                                timestamp: new Date(),
                                type: 'interrupted',
                                streamCompleted: true,
                            },
                        });
                    }
                    else {
                        scopedDispatch({
                            type: 'UPDATE_LAST_MESSAGE',
                            payload: {
                                content: finalContent,
                                displayContent: finalContent,
                                type: 'interrupted',
                                streamCompleted: true,
                            },
                        });
                    }
                    if (event.run_cost_summary !== undefined) {
                        scopedDispatch({ type: 'SET_RUN_COST_SUMMARY', payload: event.run_cost_summary });
                    }
                    scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'cancelled' });
                    scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
                    scopedDispatch({ type: 'SET_INPUT_MODE', payload: 'normal' });
                    scopedDispatch({ type: 'SET_STREAMING', payload: false });
                    break;
                }
                case 'run_failed': {
                    streamFailed = true;
                    if (event.run_cost_summary !== undefined) {
                        scopedDispatch({ type: 'SET_RUN_COST_SUMMARY', payload: event.run_cost_summary });
                    }
                    flushFrameNow();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } });
                    const failMessage = (typeof event.message === 'string' && event.message.trim())
                        ? event.message
                        : '旅行方案暂时无法生成，请稍后重试。';
                    assistantMessage.content = failMessage;
                    assistantMessage.displayContent = failMessage;
                    scopedDispatch({
                        type: 'UPDATE_LAST_MESSAGE',
                        payload: {
                            content: failMessage,
                            displayContent: failMessage,
                            type: 'error',
                            streamCompleted: true,
                            pendingStatusText: undefined,
                        },
                    });
                    scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
                    scopedDispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
                    scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'failed' });
                    scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
                    scopedDispatch({ type: 'SET_INPUT_MODE', payload: 'normal' });
                    scopedDispatch({ type: 'SET_STREAMING', payload: false });
                    scopedDispatch({ type: 'BUMP_TRIP_RUN_REFRESH' });
                    break;
                }
                case 'error':
                    streamFailed = true;
                    flushFrameNow();
                    if (!presentation.hasReceivedChunk) {
                        scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } });
                    }
                    scopedDispatch({
                        type: 'UPDATE_LAST_MESSAGE',
                        payload: {
                            content: event.message || '请求未完成，请稍后重试。',
                            displayContent: event.message || '请求未完成，请稍后重试。',
                            type: event.run_status === 'interrupted' ? 'interrupted' : 'error',
                            streamCompleted: true,
                            pendingStatusText: undefined,
                        },
                    });
                    if (event.run_cost_summary !== undefined) {
                        scopedDispatch({ type: 'SET_RUN_COST_SUMMARY', payload: event.run_cost_summary });
                    }
                    scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
                    scopedDispatch({ type: 'SET_STREAMING', payload: false });
                    if (isTripRunStatus(event.run_status)
                        && (!event.run_id || currentStateRef.current.currentTripRunId === event.run_id
                            || event.run_id === planningRunId)) {
                        scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: event.run_status });
                        scopedDispatch({ type: 'BUMP_TRIP_RUN_REFRESH' });
                    }
                    break;
            }
        } };
}
