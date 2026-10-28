import { CircleAlert, Check, Copy, RefreshCw, ShieldBan, ShieldQuestion, Square } from "lucide-react";
import { cn } from "../../../lib/utils";
import { getChatErrorGuidance } from "../model/chatErrorGuidance";
import { useApp } from "../../../app/state/AppContext";
import { type Message } from "../types/messages";
import { Markdown } from "./Markdown";
import { ThinkingChain } from "./ThinkingChain";
import { Hallmark } from "./hallmark/Hallmark";
import { InspectHint, InspectSectionTitle } from "../../../components/ui/InspectHint";
import { buildCostLedgerView } from "../model/costLedger";
import React from 'react';
const SHELL_ANSWER = 'rounded-card rounded-bl-label px-4 py-3 max-w-full break-words bg-panel border border-stroke/60 shadow-sm';
interface MessageBubbleProps {
    message: Message;
    isGenerating?: boolean;
    isLast?: boolean;
    onRetry?: () => void;
    retryDisabled?: boolean;
}
export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, isGenerating, isLast, onRetry, retryDisabled }) => {
    const { state } = useApp();
    const [copied, setCopied] = React.useState(false);
    const isUser = message.role === 'user';
    const isError = message.type === 'error';
    const isGuardBlocked = message.type === 'guard_blocked';
    const isAlertCard = isError || isGuardBlocked;
    const isWaitingApproval = message.type === 'waiting_approval';
    const isWaiting = isWaitingApproval && state.currentTripRunStatus === 'awaiting_input';
    const isInterrupted = message.type === 'interrupted';
    const steps = message.thinkingSteps || [];
    const hasDisplay = Boolean(message.displayContent?.trim());
    const hasThinking = steps.length > 0 || (!!isGenerating && !hasDisplay);
    const streaming = !!isGenerating && !message.streamCompleted && message.type !== 'interrupted';
    const regionId = `thinking-${message.id}`;
    const errorGuidance = React.useMemo(() => getChatErrorGuidance(message.displayContent || message.content || '', isGuardBlocked ? 'guard_blocked' : 'fault'), [message.content, message.displayContent, isGuardBlocked]);
    const handleErrorAction = () => {
        switch (errorGuidance.action) {
            case 'retry':
                onRetry?.();
                break;
            case 'reload':
                window.location.reload();
                break;
            case 'edit':
                document.querySelector<HTMLTextAreaElement>('[data-testid="brief-input"]')?.focus();
                break;
        }
    };
    const showErrorAction = errorGuidance.action !== null
        && (errorGuidance.action !== 'retry' || Boolean(onRetry));
    const runSummary = React.useMemo(() => !isUser && isLast && state.runCostSummary && state.runCostSummary.run_id === state.currentTripRunId
        ? state.runCostSummary
        : null, [isUser, isLast, state.runCostSummary, state.currentTripRunId]);
    const runCostLive = React.useMemo(() => !isUser && isLast && state.runCostLive && state.runCostLive.runId === state.currentTripRunId
        ? state.runCostLive
        : null, [isUser, isLast, state.runCostLive, state.currentTripRunId]);
    const serverTotalMs = isGenerating ? null : runSummary?.wall_ms ?? null;
    const costLedger = React.useMemo(() => buildCostLedgerView(runSummary, runCostLive), [runSummary, runCostLive]);
    const rawErrorText = (message.content || message.displayContent || '').trim();
    const handleCopy = async () => {
        await navigator.clipboard.writeText(message.content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };
    if (isWaitingApproval && state.planApprovalGate)
        return null;
    return (<div className={cn('flex w-full', isUser ? 'flex-row-reverse animate-slide-in-right' : 'flex-row animate-slide-up')}>
      <div className={cn('flex min-w-0 flex-col', isUser ? 'items-end max-w-[85%]' : 'items-start gap-2', !isUser && (hasThinking ? 'w-full max-w-full' : 'max-w-[85%]'))}>
        {isUser && (<div data-user-bubble className="rounded-card rounded-br-label bg-accent px-4 py-3 text-white">
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.displayContent}</p>
          </div>)}

        {isWaiting && (<div aria-live="polite" className="flex w-full min-w-0 overflow-hidden rounded-card border border-accent/15 bg-[var(--color-accent-soft)] shadow-sm">
            <div className="flex w-full items-center gap-2 px-4 py-3">
              <ShieldQuestion size={14} className="flex-shrink-0 text-accent"/>
              <span className="flex-1 text-sm font-medium leading-relaxed text-ink">等待批准方案</span>
              <span className="flex items-center gap-[5px]">
                <span className="waiting-dot inline-block h-[5px] w-[5px] rounded-full bg-accent"/>
                <span className="waiting-dot inline-block h-[5px] w-[5px] rounded-full bg-accent"/>
                <span className="waiting-dot inline-block h-[5px] w-[5px] rounded-full bg-accent"/>
              </span>
            </div>
          </div>)}


        {!isUser && !isWaiting && hasThinking && (<ThinkingChain steps={steps} isGenerating={!!isGenerating} displayContent={message.displayContent} isSynthesizing={state.isSynthesizing} pendingStatusText={message.pendingStatusText} variant={isInterrupted || isError ? 'interrupted' : 'default'} serverTotalMs={serverTotalMs} startedAt={message.timestamp} regionId={regionId}/>)}


        {isAlertCard && (<div role="alert" data-testid={isGuardBlocked ? 'guard-blocked-card' : undefined} className={cn('max-w-xl rounded-card px-4 py-4 shadow-sm sm:px-5', isGuardBlocked
                ? 'border border-stroke bg-panel'
                : 'border border-warning/20 bg-[color-mix(in_srgb,var(--color-warning)_6%,var(--color-panel))]')}>
            <div className="flex items-start gap-3">
              <div className={cn('mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full', isGuardBlocked ? 'bg-surface text-ink-secondary' : 'bg-warning/10 text-warning')}>
                {isGuardBlocked ? <ShieldBan size={16}/> : <CircleAlert size={16}/>}
              </div>
              <div className="flex min-w-0 flex-1 flex-col">
                <p className="text-sm font-semibold leading-snug text-ink">{errorGuidance.title}</p>

                {isGuardBlocked && rawErrorText && (<p className="mt-1.5 max-w-[56ch] text-sm leading-relaxed text-ink">{rawErrorText}</p>)}
                <p className="mt-1.5 max-w-[56ch] text-sm leading-relaxed text-ink-secondary">
                  {errorGuidance.description}
                </p>


                {isError && (<div className="mt-3 flex flex-wrap items-center gap-2">
                    {showErrorAction && (<button type="button" data-testid={errorGuidance.action === 'retry' ? 'retry-send' : 'error-primary-action'} data-error-action={errorGuidance.action || undefined} onClick={handleErrorAction} disabled={errorGuidance.action === 'retry' && retryDisabled} className="inline-flex items-center gap-1.5 self-start rounded-card border border-stroke bg-panel px-3.5 py-2 text-xs font-semibold text-ink shadow-sm transition-[border-color,background-color,color,transform] duration-fast ease-standard hover:border-accent/25 hover:bg-accent-soft hover:text-accent active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-stroke disabled:hover:bg-panel disabled:hover:text-ink">
                        <RefreshCw size={13}/>
                        {errorGuidance.actionLabel}
                      </button>)}
                    {rawErrorText && (<InspectHint label="技术详情" testId="error-inspect" placement="bottom-start">
                        <InspectSectionTitle>错误技术详情</InspectSectionTitle>
                        <p className="mt-2 max-h-40 overflow-y-auto break-words font-mono text-[11px] leading-relaxed text-ink-secondary">
                          {rawErrorText}
                        </p>
                      </InspectHint>)}
                  </div>)}
              </div>
            </div>
          </div>)}

        {!isUser && !isAlertCard && !isWaiting && hasDisplay && (<div data-assistant-answer className={cn(SHELL_ANSWER, 'relative')}>
            {(message.contextReport || costLedger) && (<div className="absolute right-3 top-2.5 z-10 flex items-center gap-0.5">
                <Hallmark glyph="context" data={message.contextReport}/>
                <Hallmark glyph="cost" data={costLedger}/>
              </div>)}
            <Markdown content={message.displayContent} streaming={streaming}/>
            {isInterrupted && (<div className="mt-2 flex items-center gap-1.5 border-t border-stroke pt-2">
                <Square size={10} className="text-ink-muted"/>
                <span className="text-[11px] text-ink-muted">已停止生成</span>
              </div>)}
          </div>)}

        {!isUser && !isAlertCard && !isWaiting && message.content && (<div className="mt-1.5 flex items-center gap-3 px-1">
            <button type="button" data-testid="copy-message" onClick={handleCopy} className="flex items-center gap-1 text-[11px] text-ink-muted transition-colors hover:text-ink-secondary">
              {copied ? <Check size={12} className="text-success"/> : <Copy size={12}/>}
              <span>{copied ? '已复制' : '复制'}</span>
            </button>
          </div>)}
      </div>
    </div>);
};
