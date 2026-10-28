import { optimizePrompt } from "../api/prompt";
import { compactSession } from "../api/sessions";
import { cn } from "../../../lib/utils";
import { isTripRunCancellable } from "../../travel/types/runs";
import { useApp } from "../../../app/state/AppContext";
import { Button } from "../../../components/ui/Button";
import { Tooltip } from "../../../components/ui/Tooltip";
import { Send, Square, Check, Plus, Sparkles, Loader2, Copy, X, Archive } from "lucide-react";
import { useSendMessage } from "../../../app/session/useSendMessage";
import { useSessionManager } from "../../../app/session/useSessionManager";
import { useStopRun } from "../../../app/session/useStopRun";
import { PresetSelector } from "../../presets/components/PresetSelector";
import { normalizeContextCompactionEvent } from "../model/contextCompaction";
import React, { useState, useRef, useCallback } from 'react';
export const InputArea: React.FC<{
    showCompaction?: boolean;
    minimal?: boolean;
}> = ({ showCompaction = true, minimal = false }) => {
    const { state, dispatch, activeStreamAbortRef } = useApp();
    const { sendMessage } = useSendMessage();
    const { setLastSession } = useSessionManager();
    const { stopRun } = useStopRun();
    const [input, setInput] = useState('');
    const [stoppedInput, setStoppedInput] = useState('');
    const [isOptimizing, setIsOptimizing] = useState(false);
    const [optimizedPrompt, setOptimizedPrompt] = useState<string | null>(null);
    const [optimizeError, setOptimizeError] = useState<string | null>(null);
    const [optimizeCopied, setOptimizeCopied] = useState(false);
    const [isCompacting, setIsCompacting] = useState(false);
    const [compactError, setCompactError] = useState<string | null>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const mode = state.inputMode;
    const adjustHeight = () => {
        const el = textareaRef.current;
        if (el) {
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 200) + 'px';
        }
    };
    const handleSend = useCallback(async () => {
        const text = input.trim();
        if (!text || state.isStreaming)
            return;
        setInput('');
        if (textareaRef.current)
            textareaRef.current.style.height = 'auto';
        dispatch({ type: 'SET_THINKING_STEPS', payload: [] });
        await sendMessage(text);
    }, [input, state.isStreaming, dispatch, sendMessage]);
    const handleStop = stopRun;
    const handleStoppedSend = useCallback(async () => {
        const text = stoppedInput.trim();
        if (!text)
            return;
        setStoppedInput('');
        dispatch({ type: 'SET_INPUT_MODE', payload: 'normal' });
        dispatch({ type: 'SET_THINKING_STEPS', payload: [] });
        await sendMessage(text);
    }, [stoppedInput, dispatch, sendMessage]);
    const handleNewChat = useCallback(() => {
        if (activeStreamAbortRef.current) {
            activeStreamAbortRef.current.abort();
            activeStreamAbortRef.current = null;
        }
        dispatch({ type: 'CLEAR_CHAT' });
        setLastSession(null);
        setStoppedInput('');
    }, [activeStreamAbortRef, dispatch, setLastSession]);
    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };
    const handleStoppedKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleStoppedSend();
        }
    };
    const handleOptimizePrompt = useCallback(async () => {
        const text = input.trim();
        if (!text || isOptimizing)
            return;
        setIsOptimizing(true);
        setOptimizedPrompt(null);
        setOptimizeError(null);
        try {
            const result = await optimizePrompt(text);
            if (result.success && result.optimized_prompt) {
                setOptimizedPrompt(result.optimized_prompt);
            }
            else {
                setOptimizeError(result.error_message || '请补充更多信息后重试');
            }
        }
        catch {
            setOptimizeError('优化服务暂时不可用，请稍后重试');
        }
        finally {
            setIsOptimizing(false);
        }
    }, [input, isOptimizing]);
    const handleAdoptOptimized = useCallback(() => {
        if (!optimizedPrompt)
            return;
        setInput(optimizedPrompt);
        setOptimizedPrompt(null);
        setOptimizeError(null);
        requestAnimationFrame(() => {
            const el = textareaRef.current;
            if (el) {
                el.style.height = 'auto';
                el.style.height = Math.min(el.scrollHeight, 200) + 'px';
            }
        });
    }, [optimizedPrompt]);
    const handleCopyOptimized = useCallback(async () => {
        if (!optimizedPrompt)
            return;
        await navigator.clipboard.writeText(optimizedPrompt);
        setOptimizeCopied(true);
        setTimeout(() => setOptimizeCopied(false), 2000);
    }, [optimizedPrompt]);
    const handleCloseOptimizePreview = useCallback(() => {
        setOptimizedPrompt(null);
        setOptimizeError(null);
    }, []);
    const handleCompactSession = useCallback(async () => {
        const sessionId = state.currentSessionId;
        if (!sessionId || isCompacting)
            return;
        setIsCompacting(true);
        setCompactError(null);
        try {
            const result = await compactSession(sessionId);
            const compaction = normalizeContextCompactionEvent(result);
            if (!compaction)
                throw new Error('incomplete compaction event');
            dispatch({
                type: 'ADD_MESSAGE',
                payload: {
                    id: compaction.id,
                    role: 'system',
                    content: '',
                    displayContent: '',
                    timestamp: new Date(compaction.occurredAt),
                    type: 'context_compaction',
                    contextCompaction: compaction,
                },
            });
        }
        catch {
            setCompactError('整理失败，请稍后重试');
        }
        finally {
            setIsCompacting(false);
        }
    }, [state.currentSessionId, isCompacting]);
    const runInFlight = Boolean(state.currentTripRunId && isTripRunCancellable(state.currentTripRunStatus));
    const showStop = runInFlight && (state.isStreaming || !input.trim());
    return (<div className="w-full">

      <div className="rounded-card shadow-sm">

        <div className="overflow-hidden rounded-card border border-stroke bg-panel">
          <div className="input-normal-row">
            <div className="input-normal-inner flex items-center gap-2 px-4 py-3">
              {mode === 'stopped' ? (<>
                  <textarea value={stoppedInput} onChange={(e) => setStoppedInput(e.target.value)} onKeyDown={handleStoppedKeyDown} placeholder={minimal ? '告诉我想怎么改……' : '告诉 JourneyPilot 这趟行程想怎么调整…'} rows={1} autoFocus className={cn('flex-1 bg-transparent border-none resize-none', 'text-sm text-ink placeholder:text-ink-muted', 'min-h-[24px] max-h-[120px] leading-relaxed')}/>
                  <Button variant="primary" size="sm" onClick={handleStoppedSend} disabled={!stoppedInput.trim()} className="flex-shrink-0 !rounded-card !h-8 !w-8 !p-0">
                    <Send size={14}/>
                  </Button>
                  {!minimal && <button onClick={handleNewChat} className={cn('flex-shrink-0 flex items-center gap-1.5 h-8 px-3 rounded-card', 'text-xs font-medium text-ink-secondary', 'border border-stroke/60 bg-transparent', 'hover:bg-ink/5 hover:text-ink hover:border-stroke/60', 'transition-[color,background-color,opacity] duration-base ease-standard')}>
                    <Plus size={13}/>
                    新建行程
                  </button>}
                </>) : (<>
                  <textarea ref={textareaRef} data-testid="brief-input" value={input} onChange={(e) => {
                setInput(e.target.value);
                adjustHeight();
            }} onKeyDown={handleKeyDown} placeholder={minimal ? '告诉我想怎么改……' : '描述这趟旅行：目的地、日期、同行人、预算、偏好…'} rows={1} name="chat-message" autoComplete="off" autoFocus={minimal} className={cn('flex-1 bg-transparent border-none resize-none', 'text-sm text-ink placeholder:text-ink-muted', 'min-h-[24px] max-h-[200px] leading-relaxed')}/>
                  <Button variant="primary" size="sm" data-testid="send-button" aria-label={showStop ? '停止本次运行' : '发送'} data-streaming={showStop ? 'true' : 'false'} onClick={showStop ? handleStop : handleSend} disabled={!showStop && !input.trim()} className={cn('flex-shrink-0 !rounded-card !h-8 !w-8 !p-0', showStop &&
                '!bg-ink/75 hover:!bg-ink !shadow-none')}>
                    {showStop ? <Square size={13}/> : <Send size={14}/>}
                  </Button>
                </>)}
            </div>
          </div>
        </div>
      </div>


      {!minimal && (<div className={cn('flex flex-wrap items-center gap-2 mt-2 px-1 [&>*]:shrink-0', 'transition-[color,background-color,opacity] duration-base ease-standard', mode !== 'normal'
            ? 'opacity-0 pointer-events-none h-0 mt-0 overflow-hidden'
            : 'opacity-100 h-auto')}>

        {!state.currentTripRunId && <PresetSelector />}

        <Tooltip content="把描述补全成更清楚的行程需求" position="top">
          <button onClick={handleOptimizePrompt} disabled={!input.trim() || isOptimizing} className={cn('flex items-center gap-1.5 px-2.5 py-1.5 rounded-card text-xs font-medium whitespace-nowrap', 'transition-[color,background-color,opacity] duration-base ease-standard', input.trim() && !isOptimizing
            ? 'bg-transparent text-ink-secondary border border-[rgba(38,36,32,0.14)] hover:text-accent hover:border-[color-mix(in_srgb,var(--color-accent)_40%,transparent)]'
            : isOptimizing
                ? 'bg-transparent text-accent border border-[color-mix(in_srgb,var(--color-accent)_40%,transparent)] cursor-not-allowed'
                : 'bg-ink/5 text-ink-muted border border-transparent cursor-not-allowed')}>
            {isOptimizing
            ? <Loader2 size={14} className="animate-spin"/>
            : <Sparkles size={14}/>}
            {isOptimizing ? '补全中…' : '补全行程描述'}
          </button>
        </Tooltip>

        {showCompaction && (<Tooltip content="整理后的要点会继续用于规划" position="top">
            <button data-testid="compact-session" onClick={handleCompactSession} disabled={!state.currentSessionId || isCompacting || state.isStreaming} className={cn('flex items-center gap-1.5 px-2.5 py-1.5 rounded-card text-xs font-medium whitespace-nowrap', 'transition-[color,background-color,opacity] duration-base ease-standard', state.currentSessionId && !isCompacting && !state.isStreaming
                ? 'bg-warning/10 text-warning border border-warning/30 hover:bg-warning/15 hover:border-warning/40'
                : 'bg-ink/5 text-ink-muted border border-transparent cursor-not-allowed')}>
              {isCompacting
                ? <Loader2 size={14} className="animate-spin"/>
                : <Archive size={14}/>}
              {isCompacting ? '整理中…' : '整理较早对话'}
            </button>
          </Tooltip>)}
      </div>)}


      <div className={cn('input-expand', (optimizedPrompt !== null || optimizeError !== null) && 'expanded')}>
        <div className="input-expand-content">
          {(optimizedPrompt !== null || optimizeError !== null) && (<div className={cn('mt-2 overflow-hidden rounded-card border bg-panel', 'shadow-[0_1px_0_rgba(42,38,26,0.03),0_8px_22px_rgba(42,38,26,0.07)]', optimizeError
                ? 'border-error/20 bg-error/[0.02]'
                : 'border-accent/15')}>
              {optimizeError ? (<div className="px-4 py-3 flex items-start gap-2.5">
                  <Sparkles size={14} className="text-error flex-shrink-0 mt-0.5"/>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-error mb-0.5">没能补全</p>
                    <p className="text-xs text-error leading-relaxed">{optimizeError}</p>
                  </div>
                  <button type="button" onClick={handleCloseOptimizePreview} className="flex-shrink-0 text-ink-muted hover:text-ink-secondary transition-colors">
                    <X size={14}/>
                  </button>
                </div>) : (<div className="px-4 pt-3 pb-3">
                  <div className="flex items-center gap-1.5 mb-2">
                    <Sparkles size={12} className="text-accent flex-shrink-0"/>
                    <span className="text-[11px] font-medium text-accent">补全后的描述</span>
                    <div className="flex-1"/>
                    <button type="button" onClick={handleCloseOptimizePreview} className="text-ink-muted hover:text-ink-secondary transition-colors">
                      <X size={13}/>
                    </button>
                  </div>
                  <div className={cn('text-sm text-ink leading-relaxed rounded-card px-3 py-2.5 mb-3', 'bg-accent-soft border border-accent/10', 'max-h-[150px] overflow-y-auto')}>
                    {optimizedPrompt}
                  </div>
                  <div className="flex items-center gap-2 justify-end">
                    <button onClick={handleCopyOptimized} className={cn('flex items-center gap-1.5 px-2.5 py-1.5 rounded-card text-xs font-medium whitespace-nowrap', 'transition-[color,background-color,opacity] duration-base ease-standard', 'border border-stroke/60 bg-transparent', 'hover:bg-ink/5 hover:border-stroke text-ink-secondary')}>
                      {optimizeCopied
                    ? <Check size={12} className="text-success"/>
                    : <Copy size={12}/>}
                      {optimizeCopied ? '已复制' : '复制'}
                    </button>
                    <button onClick={handleAdoptOptimized} className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-card text-xs font-medium', 'transition-[color,background-color,opacity] duration-base ease-standard', 'bg-accent text-white hover:bg-accent-hover shadow-sm')}>
                      采用
                    </button>
                  </div>
                </div>)}
            </div>)}
        </div>
      </div>
      {compactError && (<p role="status" className="mt-2 px-1 text-xs text-error">
          {compactError}
        </p>)}
    </div>);
};
