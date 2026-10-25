import { AnimatePresence, m } from "motion/react";
import { cn } from "../../../lib/utils";
import { groupByDate } from "../model/sessionGrouping";
import { useApp } from "../../../app/state/AppContext";
import { useSessionManager } from "../../../app/session/useSessionManager";
import { useIsMobileViewport } from "../../../hooks/useMediaQuery";
import { MessageSquare, Pencil, Route, Trash2, X } from "lucide-react";
import { parseSessionTitle } from "../model/sessionTitle";
import { describeRequestFailure } from "../../../lib/requestFailureMessage";
import { Button } from "../../../components/ui/Button";
import { ConfirmAction } from "../../../components/ui/ConfirmAction";
import { duration, easing } from "../../../lib/motion";
import { type ChatSession } from "../types/messages";
import React from 'react';
interface ConversationListProps {
    searchQuery: string;
}
const RECORD_SLOT = 'flex w-10 shrink-0 justify-center pt-[3px]';
const SessionRecord: React.FC<{
    title: string;
}> = ({ title }) => {
    const parsed = parseSessionTitle(title);
    if (parsed.kind === 'plain') {
        return (<>
        <span className={RECORD_SLOT}>
          <MessageSquare size={14} className="opacity-50" aria-hidden/>
        </span>
        <span data-session-shape="plain" data-session-field="text" className="min-w-0 flex-1 break-words text-sm leading-[1.35] line-clamp-2">
          {parsed.text}
        </span>
      </>);
    }
    return (<>
      <span className={RECORD_SLOT}>
        <Route size={14} className="opacity-50" aria-hidden/>
      </span>
      <span data-session-shape="trip" className="min-w-0 flex-1" aria-label={title}>
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-1 text-sm leading-[1.35]">
          {parsed.origin && (<>
              <span data-session-field="origin" className="min-w-0 break-words text-ink-secondary">
                {parsed.origin}
              </span>

              <span className="shrink-0 text-chart" aria-hidden>→</span>
            </>)}
          <span data-session-field="destination" className="min-w-0 break-words font-semibold">
            {parsed.destination}
          </span>
        </span>
        {parsed.dates && (<span data-session-field="dates" className="mt-0.5 block font-mono text-[11px] tabular-nums text-ink-muted">
            {parsed.dates}
          </span>)}
      </span>
    </>);
};
export const ConversationList: React.FC<ConversationListProps> = ({ searchQuery }) => {
    const { state, dispatch } = useApp();
    const { openSession, deleteSession, renameSession } = useSessionManager();
    const { sessions, currentSessionId } = state;
    const isMobile = useIsMobileViewport();
    const [editingId, setEditingId] = React.useState<string | null>(null);
    const [draft, setDraft] = React.useState('');
    const [renameError, setRenameError] = React.useState<string | null>(null);
    const inputRef = React.useRef<HTMLInputElement>(null);
    const settledRef = React.useRef(false);
    const filtered = searchQuery
        ? sessions.filter((s) => s.title.toLowerCase().includes(searchQuery.toLowerCase()))
        : sessions;
    const beginEdit = (session: ChatSession) => {
        setRenameError(null);
        settledRef.current = false;
        setEditingId(session.id);
        setDraft(session.title);
        requestAnimationFrame(() => {
            inputRef.current?.focus();
            inputRef.current?.select();
        });
    };
    const cancelEdit = () => {
        settledRef.current = true;
        setEditingId(null);
        setDraft('');
    };
    const commitEdit = (session: ChatSession) => {
        if (settledRef.current)
            return;
        settledRef.current = true;
        const next = draft.trim();
        setEditingId(null);
        setDraft('');
        if (!next || next === session.title)
            return;
        setRenameError(null);
        void renameSession(session.id, next).catch((err) => {
            setRenameError(describeRequestFailure(err, '重命名', '这个行程').message);
        });
    };
    if (filtered.length === 0) {
        return (<div className="flex h-full min-h-[8rem] flex-col items-center justify-center text-ink-secondary">
        <MessageSquare size={24} className="mb-2 opacity-40"/>
        <span className="text-xs">{searchQuery ? '无匹配结果' : '暂无对话'}</span>
      </div>);
    }
    const sections: Array<[
        string,
        ChatSession[]
    ]> = [...groupByDate(filtered)];
    return (<div className="space-y-4 pb-2">
      {renameError && (<div className="ml-[46px] mr-2 rounded-card bg-error/10 px-2.5 py-1.5 text-[11px] leading-snug text-error">
          {renameError}
        </div>)}
      {sections.map(([label, items]) => {
            return (<div key={label}>
            <div className="py-1 pl-[46px] text-[11px] font-medium uppercase tracking-wider text-ink-secondary">
              {label}
            </div>
            <div className="space-y-0.5">
              <AnimatePresence initial={false}>
                {items.map((session) => {
                    const isEditing = editingId === session.id;
                    return (<m.div key={session.id} layout={false} exit={{
                            opacity: 0,
                            y: -4,
                            transition: { duration: duration.base, ease: easing.accelerate },
                        }}>
                      <div className={cn('group flex items-center gap-1 rounded-card', session.id === currentSessionId ? 'bg-accent/8 text-accent' : 'text-ink')}>
                        {isEditing ? (<div className="flex min-w-0 flex-1 items-center gap-1 py-1.5 pl-[46px] pr-2">
                            <input ref={inputRef} data-testid="rename-input" value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={() => commitEdit(session)} onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault();
                                    commitEdit(session);
                                }
                            }} maxLength={32} className={cn('flex-1 min-w-0 rounded-card bg-panel/70 px-1.5 py-1 text-sm text-ink', 'border border-accent/60', '')}/>

                            <button type="button" data-testid="rename-cancel" onMouseDown={(e) => {
                                e.preventDefault();
                                cancelEdit();
                            }} className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-card text-ink-secondary transition-colors duration-fast ease-standard hover:bg-ink/8 hover:text-ink">
                              <X size={13}/>
                            </button>
                          </div>) : (<>
                            <button type="button" className={cn('touch-row flex flex-1 min-w-0 items-start gap-0 rounded-card py-2 pl-1.5 pr-2 text-left', 'transition-colors duration-fast ease-standard', session.id === currentSessionId
                                ? 'text-accent'
                                : 'hover:bg-ink/[0.04]')} onClick={() => {
                                dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'chat' });
                                void openSession(session.id);
                                if (isMobile)
                                    dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true });
                            }}>
                              <SessionRecord title={session.title}/>
                            </button>

                            <div className="coarse-show coarse-cluster flex flex-shrink-0 items-center gap-0.5 opacity-0 transition-opacity duration-fast ease-standard group-hover:opacity-100">

                              <Button variant="icon" size="sm" data-testid="rename-session" aria-label={`重命名「${session.title}」`} className="coarse-op !h-6 !w-6" onClick={() => beginEdit(session)}>
                                <Pencil size={12}/>
                              </Button>
                              <ConfirmAction testId="delete-session" onConfirm={() => {
                                void deleteSession(session.id);
                            }} confirmLabel="删除" triggerLabel={`删除「${session.title}」`} triggerClassName="coarse-op" className="border-transparent bg-transparent !px-0 !py-0">
                                <Trash2 size={12}/>
                              </ConfirmAction>
                            </div>
                          </>)}
                      </div>
                    </m.div>);
                })}
              </AnimatePresence>
            </div>
          </div>);
        })}
    </div>);
};
