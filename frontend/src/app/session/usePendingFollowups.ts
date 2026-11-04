import { useCallback, useEffect } from 'react';
import { generateId } from '../../lib/utils';
import { useApp } from '../state/AppContext';
import { formatPendingFollowups } from './pendingFollowups';
import { useSendMessage } from './useSendMessage';

export function usePendingFollowups() {
    const { state, currentStateRef, pendingFollowups, setPendingFollowups } = useApp();
    const sessionId = state.currentSessionId;
    const items = sessionId ? pendingFollowups[sessionId] ?? [] : [];

    const add = useCallback((text: string) => {
        const current = currentStateRef.current;
        const content = text.trim();
        if (!content || !sessionId || !state.deliveryBundle || state.currentTripRunReadOnly
            || current.currentSessionId !== sessionId)
            return false;
        const id = sessionId;
        const status = state.isStreaming || state.currentTripRunStatus === 'running'
            || state.currentTripRunStatus === 'created' ? 'waiting' : 'paused';
        setPendingFollowups(previous => ({
            ...previous,
            [id]: [...(previous[id] ?? []).map(item => ({ ...item, messageId: undefined })), { id: generateId(), text: content, status }],
        }));
        return true;
    }, [currentStateRef, sessionId, setPendingFollowups, state.currentTripRunReadOnly, state.currentTripRunStatus, state.deliveryBundle, state.isStreaming]);

    const update = useCallback((id: string, text: string) => {
        if (!sessionId) return;
        setPendingFollowups(previous => ({
            ...previous,
            [sessionId]: (previous[sessionId] ?? []).map(item => ({
                ...item, text: item.id === id ? text : item.text, messageId: undefined,
            })),
        }));
    }, [sessionId, setPendingFollowups]);

    const setEditing = useCallback((id: string, editing: boolean) => {
        if (!sessionId) return;
        setPendingFollowups(previous => ({
            ...previous,
            [sessionId]: (previous[sessionId] ?? []).map(item => item.id === id
                ? { ...item, editing, status: editing && item.status === 'ready' ? 'paused' : item.status }
                : item),
        }));
    }, [sessionId, setPendingFollowups]);

    const remove = useCallback((id: string) => {
        if (!sessionId) return;
        setPendingFollowups(previous => ({
            ...previous,
            [sessionId]: (previous[sessionId] ?? []).filter(item => item.id !== id).map(item => ({ ...item, messageId: undefined })),
        }));
    }, [sessionId, setPendingFollowups]);

    const resume = useCallback(() => {
        if (!sessionId) return;
        setPendingFollowups(previous => ({
            ...previous,
            [sessionId]: (previous[sessionId] ?? []).map(item => ({ ...item, status: 'ready' })),
        }));
    }, [sessionId, setPendingFollowups]);

    return { items, add, update, setEditing, remove, resume };
}

export function usePendingFollowupDispatch() {
    const { state, currentStateRef, pendingFollowups, pendingFollowupsRef, setPendingFollowups } = useApp();
    const { sendMessage } = useSendMessage();
    const sessionId = state.currentSessionId;

    useEffect(() => {
        if (!sessionId || state.isStreaming || !state.deliveryBundle || state.currentTripRunReadOnly
            || state.planApprovalGate || state.understandingQuestions || state.pendingRouteConfirmation
            || state.currentTripRunStatus === 'running' || state.currentTripRunStatus === 'created'
            || state.currentTripRunStatus === 'awaiting_input' || state.currentTripRunStatus === 'cancel_requested') return;
        const waiting = pendingFollowupsRef.current[sessionId] ?? [];
        if (!waiting.length || waiting.some(item => item.status !== 'ready' || item.editing || !item.text.trim())) return;
        const text = formatPendingFollowups(waiting);
        const messageId = waiting[0].messageId ?? generateId();
        const ids = new Set(waiting.map(item => item.id));
        setPendingFollowups(previous => ({
            ...previous,
            [sessionId]: (previous[sessionId] ?? []).filter(item => !ids.has(item.id)),
        }));
        const runId = state.deliveryBundle.manifest.run_id;
        const restore = () => setPendingFollowups(previous => {
            const later = previous[sessionId] ?? [];
            return {
                ...previous,
                [sessionId]: [
                    ...waiting.map(item => ({ ...item, messageId: later.length ? undefined : messageId, status: 'paused' as const })),
                    ...later.map(item => ({ ...item, messageId: undefined })),
                ],
            };
        });
        void sendMessage(text, { resumeRunId: runId, messageId, requireResponse: true })
            .then(sent => {
                if (!sent) {
                    restore();
                    return;
                }
                setPendingFollowups(previous => ({
                    ...previous,
                    [sessionId]: (previous[sessionId] ?? []).map(item => (
                        item.status === 'waiting' && !currentStateRef.current.isStreaming
                            ? { ...item, status: 'paused' } : item
                    )),
                }));
            })
            .catch(restore);
    }, [
        currentStateRef, pendingFollowups, pendingFollowupsRef, sendMessage,
        sessionId, setPendingFollowups, state.currentTripRunReadOnly, state.currentTripRunStatus,
        state.deliveryBundle, state.isStreaming, state.pendingRouteConfirmation,
        state.planApprovalGate, state.understandingQuestions,
    ]);
}
