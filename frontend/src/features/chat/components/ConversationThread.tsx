import { AnimatePresence, m, useIsPresent } from "motion/react";
import { useApp } from "../../../app/state/AppContext";
import { useSendMessage } from "../../../app/session/useSendMessage";
import { useSessionManager } from "../../../app/session/useSessionManager";
import { cn } from "../../../lib/utils";
import { duration, easing } from "../../../lib/motion";
import { projectVisibleMessages } from "../model/conversationFlow";
import { InputArea } from "./InputArea";
import { MessageBubble } from "./MessageBubble";
import { ContextCompactionNotice } from "./ContextCompactionNotice";
import { TripPlanner, type PlannerInspiration } from "../../travel/components/planning/TripPlanner";
import { TripBriefPlanGate } from "../../travel/components/planning/TripBriefPlanGate";
import { DiscoveryToIntake } from "../../travel/components/planning/DiscoveryToIntake";
import { TravelAtlas } from "../../travel/components/planning/TravelAtlas";
import type { AtlasScene } from "../../travel/components/planning/TravelAtlasScenes";
import React from 'react';
export const HeroEmptyState: React.FC<{
    homeFlowActive?: boolean;
    homePendingLabel?: string;
    homeError?: string;
    onHomePlanSubmitted?: () => void;
}> = ({ homeFlowActive = false, homePendingLabel = '', homeError = '', onHomePlanSubmitted }) => {
    const [inspiration, setInspiration] = React.useState<PlannerInspiration | null>(null);
    const useInspiration = (scene: AtlasScene) => {
        setInspiration((previous) => ({ id: (previous?.id ?? 0) + 1, text: scene.prompt, scene }));
    };
    return (<div className="new-trip-hero" data-testid="new-trip-hero">
      <div className="new-trip-main hero-scroll">
        <div className="new-trip-content">
          <header className="new-trip-copy">
            <h1>想去哪里，告诉我<span>。</span></h1>
          </header>
          <TripPlanner
            inspiration={inspiration}
            homeFlowActive={homeFlowActive}
            homePendingLabel={homePendingLabel}
            homeError={homeError}
            onHomePlanSubmitted={onHomePlanSubmitted}
          />
        </div>
      </div>
      <TravelAtlas onUseExample={useInspiration} />
    </div>);
};
export const ConversationThread: React.FC<{
    embedded?: boolean;
    initialInput?: string;
    targetRunId?: string | null;
    onInputSent?: () => void;
}> = ({ embedded = false, initialInput = '', targetRunId, onInputSent }) => {
    const { state, dispatch } = useApp();
    const { sendMessage } = useSendMessage();
    const { loadEarlierHistory } = useSessionManager();
    const isPresent = useIsPresent();
    const messages = state.currentMessages;
    const planGatePending = Boolean(state.planApprovalGate && state.planApprovalGate.status !== 'cancelled');
    const visibleMessages = React.useMemo(() => projectVisibleMessages(messages, { planGatePending }), [messages, planGatePending]);
    const isEmpty = messages.length === 0 && !state.pendingRouteConfirmation;
    const hasJourneyWorkspace = state.workspaceActive || state.deliveryBundle !== null || state.currentTripRunId !== null;
    const [homePlanning, setHomePlanning] = React.useState(false);
    React.useEffect(() => {
        setHomePlanning(false);
    }, [state.conversationEpoch]);
    React.useEffect(() => {
        if (!homePlanning) return;
        if (state.pendingRouteConfirmation || state.lastRouteDecision) {
            setHomePlanning(false);
            return;
        }
        if (!state.isStreaming) {
            const last = messages[messages.length - 1];
            if (last?.type !== 'error') setHomePlanning(false);
        }
    }, [homePlanning, messages, state.isStreaming, state.lastRouteDecision, state.pendingRouteConfirmation]);
    const lastAssistant = React.useMemo(() => [...messages].reverse().find((message) => message.role === 'assistant'), [messages]);
    const homeView = React.useMemo(() => {
        const homeFlowActive = !hasJourneyWorkspace && homePlanning;
        return {
            flowActive: homeFlowActive,
            show: !hasJourneyWorkspace && (isEmpty || homeFlowActive),
            pendingLabel: state.isStreaming ? lastAssistant?.pendingStatusText || '正在理解你的旅行想法' : '',
            error: lastAssistant?.type === 'error' ? (lastAssistant.displayContent || lastAssistant.content) : '',
        };
    }, [hasJourneyWorkspace, homePlanning, isEmpty, lastAssistant, state.isStreaming]);
    // 图形离场期间状态仍会前进：保留离开前最后一次首页内容，避免旧帧在退场动画里变成聊天页。
    const homeViewRef = React.useRef(homeView);
    if (isPresent) homeViewRef.current = homeView;
    const presentedHome = isPresent ? homeView : homeViewRef.current;
    const showHome = presentedHome.show;
    const showCanvas = state.canvasOpen && state.deliveryBundle !== null;
    const lastUserText = React.useMemo(() => {
        for (let i = visibleMessages.length - 1; i >= 0; i -= 1) {
            if (visibleMessages[i].role === 'user')
                return visibleMessages[i].content;
        }
        return null;
    }, [visibleMessages]);
    const retryLastUserMessage = React.useCallback(() => {
        if (!lastUserText || state.isStreaming)
            return;
        const runId = targetRunId ?? state.currentTripRunId;
        void sendMessage(lastUserText, runId
            ? { resumeRunId: runId, route: 'trip_refinement' }
            : state.lastRouteDecision ? { route: state.lastRouteDecision.route } : undefined);
    }, [lastUserText, sendMessage, state.isStreaming, state.currentTripRunId, state.lastRouteDecision, targetRunId]);
    const scrollRef = React.useRef<HTMLDivElement>(null);
    const stickRef = React.useRef(true);
    const restoreAnchorRef = React.useRef<{
        fromBottom: number;
        length: number;
    } | null>(null);
    const lastMessage = visibleMessages[visibleMessages.length - 1];
    const lastLen = lastMessage?.displayContent?.length ?? 0;
    const lastSteps = lastMessage?.thinkingSteps?.length ?? 0;
    const { hasMore: hasEarlierHistory, loading: loadingEarlierHistory } = state.historyPaging;
    const visibleCount = visibleMessages.length;
    const requestEarlierHistory = React.useCallback(() => {
        const el = scrollRef.current;
        if (!el || !hasEarlierHistory)
            return;
        restoreAnchorRef.current = { fromBottom: el.scrollHeight - el.scrollTop, length: visibleCount };
        void loadEarlierHistory();
    }, [hasEarlierHistory, loadEarlierHistory, visibleCount]);
    const handleScroll = () => {
        const el = scrollRef.current;
        if (!el)
            return;
        stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
        if (el.scrollTop < 200)
            requestEarlierHistory();
    };
    React.useLayoutEffect(() => {
        const el = scrollRef.current;
        if (!el)
            return;
        const anchor = restoreAnchorRef.current;
        if (anchor !== null) {
            if (visibleMessages.length === anchor.length)
                return;
            restoreAnchorRef.current = null;
            el.scrollTop = el.scrollHeight - anchor.fromBottom;
            return;
        }
        if (!stickRef.current)
            return;
        el.scrollTop = el.scrollHeight;
    }, [visibleMessages.length, lastLen, lastSteps, state.isStreaming, state.planApprovalGate]);
    const body = showHome && !embedded ? (<div className="flex h-full flex-col">
      <HeroEmptyState
        homeFlowActive={presentedHome.flowActive}
        homePendingLabel={presentedHome.pendingLabel}
        homeError={presentedHome.error}
        onHomePlanSubmitted={() => setHomePlanning(true)}
      />
    </div>) : (<div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">

        <div className={cn('mx-auto flex flex-col gap-6', embedded ? 'max-w-none' : 'max-w-3xl')}>
          {hasEarlierHistory && (<div className="flex justify-center">
              <button type="button" onClick={requestEarlierHistory} disabled={loadingEarlierHistory} className="min-h-9 rounded-card border border-stroke px-3 text-xs text-ink-secondary hover:border-accent hover:text-accent disabled:opacity-60">
                {loadingEarlierHistory ? '正在载入更早的对话…' : '载入更早的对话'}
              </button>
            </div>)}
          {visibleMessages.map((message, index) => {
            if (message.type === 'context_compaction' && message.contextCompaction) {
                return (<ContextCompactionNotice key={message.id} event={message.contextCompaction}/>);
            }
            const isLast = index === visibleMessages.length - 1;
            const isGenerating = isLast && state.isStreaming && message.role === 'assistant';
            const canRetry = message.type === 'error' && !!lastUserText;
            return (<MessageBubble key={message.id} message={message} isGenerating={isGenerating} isLast={isLast} onRetry={canRetry ? retryLastUserMessage : undefined} retryDisabled={state.isStreaming}/>);
        })}
          {planGatePending && <TripBriefPlanGate />}
          {state.pendingRouteConfirmation && (<section className="rounded-card border border-stroke bg-panel p-4 shadow-sm sm:p-5" aria-labelledby="route-confirmation-title">
              <h2 id="route-confirmation-title" className="text-xl font-semibold text-ink">你希望我先做哪件事？</h2>
              <p className="mt-1 text-sm text-ink-secondary">这句话可能有两种理解。</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {[state.pendingRouteConfirmation.decision.route, ...state.pendingRouteConfirmation.decision.alternatives.map((item) => item.route)]
                .filter((route, index, all) => all.indexOf(route) === index)
                .slice(0, 2)
                .map((route) => {
                const labels = {
                    trip_planning: '开始规划一趟旅行',
                    destination_discovery: '先推荐并比较目的地',
                    fast_answer: '只回答这个问题',
                    trip_refinement: '调整当前行程',
                } as const;
                return <button key={route} type="button" className="min-h-11 rounded-card border border-stroke bg-surface px-4 text-sm font-medium text-ink hover:border-accent hover:text-accent" onClick={() => {
                        const pending = state.pendingRouteConfirmation;
                        if (!pending)
                            return;
                        dispatch({ type: 'SET_ROUTE_CONFIRMATION', payload: null });
                        void sendMessage(pending.rawInput, {
                            route,
                            routeDecision: { ...pending.decision, route, confidence: 1, requires_trip_draft: route === 'trip_planning', requires_confirmation: false, signals: [...pending.decision.signals, 'user_confirmed_route'] },
                            displayText: labels[route],
                            assistantPendingLabel: route === 'destination_discovery' ? '正在推荐目的地' : route === 'trip_planning' ? '正在整理旅行信息' : route === 'trip_refinement' ? '正在调整行程' : '正在回答问题',
                        });
                    }}>{labels[route]}</button>;
            })}
              </div>
            </section>)}
          {state.lastRouteDecision?.route === 'destination_discovery' && !state.isStreaming && !state.currentTripRunId && (<DiscoveryToIntake rawInput={lastUserText || ''}/>)}
        </div>
      </div>

      {!planGatePending && (<div className={cn('px-4 py-3 sm:px-6', showCanvas && 'border-t border-stroke bg-surface/50')}>
          <div className="mx-auto max-w-3xl">
            {!state.pendingRouteConfirmation && <InputArea minimal={embedded} showCompaction={!embedded} initialInput={initialInput} targetRunId={targetRunId} onInputSent={onInputSent}/>}
          </div>
        </div>)}
    </div>);
    return (<AnimatePresence mode="wait" initial={false}>
      <m.div key={state.conversationEpoch} className="flex h-full min-h-0 flex-col" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0, transition: { duration: duration.base, ease: easing.decelerate } }} exit={{ opacity: 0, transition: { duration: duration.fast, ease: easing.accelerate } }}>
        {body}
      </m.div>
    </AnimatePresence>);
};
