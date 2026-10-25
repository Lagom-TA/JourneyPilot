import { type AppState } from "../state/state";
import { normalizeTripSummaryCard } from "../../features/travel/model/tripSummaryCard";
import { normalizePlanApprovalGate } from "../../features/travel/model/planApprovalGate";
import { type FinalAnswerCitation, type InformationAnnotation } from "../../features/chat/types/citations";
import { type Message } from "../../features/chat/types/messages";
import { type SSEEvent } from "../../features/chat/types/events";
import { isTripRunStatus } from "../../features/travel/types/runs";
import { type JourneyRoute } from "../../features/travel/types/planner";
import { type MutableRefObject } from "react";
import { type StreamOwnership } from "./streamOwnership";
import { createStreamPresentation } from "../../features/chat/model/streamPresentation";
import { createDeliveryProtocol } from "../../features/travel/model/deliveryProtocol";
import { type StreamFrameBatch } from "../../features/chat/model/streamFrameBatch";
export function createStreamEvents(ownership: StreamOwnership, assistantMessage: Message, text: string, initialCurrentTripRunId: string | null, pendingLabel: string | undefined, currentStateRef: MutableRefObject<AppState>, setLastSession: (id: string | null) => void, frame: StreamFrameBatch) {
    const { identity, scopedDispatch, isStreamVisible, updateActiveStreamHandle } = ownership;
    const { flushFrameNow } = frame;
    let intakeOnly = false;
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
        flushFrameNow();
        scopedDispatch({
            type: 'FINISH_LAST_THINKING_STEP',
            payload: { endTime: new Date(), tsMs: terminal.ts_ms },
        });
        if (!assistantMessage.content.trim()) {
            const readyMessage = '旅行方案已准备好，可在右侧查看完整报告与行程。';
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
    return { protocol, handleEvent(event: SSEEvent) {
            if (presentation.handle(event))
                return;
            switch (event.type) {
                case 'guided_intake':
                    if (event.guided_intake) {
                        intakeOnly = true;
                        scopedDispatch({ type: 'SET_LAST_ROUTE_DECISION', payload: event.guided_intake.route_decision });
                        scopedDispatch({ type: 'SET_ROUTE_CONFIRMATION', payload: null });
                        scopedDispatch({ type: 'SET_GUIDED_INTAKE', payload: event.guided_intake });
                        scopedDispatch({ type: 'REMOVE_MESSAGE_BY_ID', payload: assistantMessage.id });
                    }
                    break;
                case 'route_confirmation':
                    intakeOnly = true;
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
                        if (event.route_decision?.route === 'trip_planning' || event.route_decision?.route === 'trip_refinement') {
                            scopedDispatch({
                                type: 'SET_CURRENT_TRIP_RUN',
                                payload: {
                                    runId: event.run_id,
                                    source: 'live',
                                    status: 'running',
                                },
                            });
                        }
                    }
                    if (event.message_id && event.message_id !== assistantMessage.id) {
                        scopedDispatch({
                            type: 'REMAP_MESSAGE_ID',
                            payload: { fromId: assistantMessage.id, toId: event.message_id },
                        });
                        assistantMessage.id = event.message_id;
                    }
                    break;
                case 'trip_summary_card': {
                    const card = normalizeTripSummaryCard(event);
                    if (card)
                        scopedDispatch({ type: 'SET_TRIP_SUMMARY_CARD', payload: card });
                    break;
                }
                case 'approval_gate_raised': {
                    flushFrameNow();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } });
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
                    if (intakeOnly)
                        break;
                    flushFrameNow();
                    scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date(), tsMs: event.ts_ms } });
                    const citations: FinalAnswerCitation[] = (event.citations || []).map((citation) => ({
                        citationId: citation.citation_id,
                        claimText: citation.claim_text,
                        sources: (citation.sources || []).map((source) => ({
                            title: source.title,
                            url: source.url,
                            sourceName: source.source_name,
                            snippet: source.snippet,
                            authorityLabel: source.authority_label,
                            retrievedAt: source.retrieved_at,
                        })),
                    })).filter((citation) => citation.citationId && citation.sources.length > 0);
                    const annotations: InformationAnnotation[] = (event.annotations || []).map((annotation) => ({
                        annotationId: annotation.annotation_id,
                        kind: annotation.kind,
                        label: annotation.label,
                        detail: annotation.detail,
                    })).filter((annotation) => annotation.annotationId && annotation.label);
                    assistantMessage.citations = citations;
                    assistantMessage.annotations = annotations;
                    if (event.final_content && typeof event.final_content === 'string') {
                        assistantMessage.content = event.final_content;
                        assistantMessage.displayContent = event.final_content;
                        scopedDispatch({
                            type: 'UPDATE_LAST_MESSAGE',
                            payload: {
                                content: event.final_content,
                                displayContent: event.final_content,
                                citations,
                                annotations,
                                streamCompleted: true,
                            },
                        });
                    }
                    else {
                        scopedDispatch({
                            type: 'UPDATE_LAST_MESSAGE',
                            payload: { citations, annotations, streamCompleted: true },
                        });
                    }
                    if (event.run_id) {
                        scopedDispatch({
                            type: 'SET_CURRENT_TRIP_RUN',
                            payload: {
                                runId: event.run_id || initialCurrentTripRunId,
                                source: 'live',
                            },
                        });
                    }
                    if (event.run_cost_summary !== undefined) {
                        scopedDispatch({ type: 'SET_RUN_COST_SUMMARY', payload: event.run_cost_summary });
                    }
                    if (event.run_status !== 'awaiting_input') {
                        scopedDispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
                        scopedDispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
                    }
                    if (isTripRunStatus(event.run_status)) {
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
                        : '已取消当前规划。已产生的阶段性内容会保留在本次 Trip Run 记录中。';
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
                    flushFrameNow();
                    if (!presentation.hasReceivedChunk) {
                        scopedDispatch({ type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } });
                    }
                    scopedDispatch({
                        type: 'UPDATE_LAST_MESSAGE',
                        payload: {
                            content: event.message || '发生错误',
                            displayContent: event.message || '发生错误',
                            type: 'error',
                            streamCompleted: true,
                        },
                    });
                    scopedDispatch({ type: 'SET_SYNTHESIZING', payload: false });
                    scopedDispatch({ type: 'SET_STREAMING', payload: false });
                    if (isTripRunStatus(event.run_status)) {
                        scopedDispatch({ type: 'SET_TRIP_RUN_STATUS', payload: event.run_status });
                        scopedDispatch({ type: 'BUMP_TRIP_RUN_REFRESH' });
                    }
                    break;
            }
        } };
}
