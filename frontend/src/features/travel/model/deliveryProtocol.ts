import { getTripRunEventWindow } from "../api/runs";
import { isPublicDeliveryBundle, type PublicDeliveryBundle } from "../types/delivery";
import { type SSEEvent } from "../../chat/types/events";
function canonicalJson(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
    }
    if (value && typeof value === 'object') {
        const record = value as Record<string, unknown>;
        return `{${Object.keys(record).sort().map((key) => (`${JSON.stringify(key)}:${canonicalJson(record[key])}`)).join(',')}}`;
    }
    return JSON.stringify(value);
}
export function createDeliveryProtocol(identity: {
    sessionId: string | null;
    runId: string | null;
}, onReady: (bundle: PublicDeliveryBundle) => void, onFinalized: (terminal: SSEEvent) => void) {
    let confirmedDeliveryBundle: PublicDeliveryBundle | null = null;
    let deliveryReadyEvent: SSEEvent | null = null;
    let deliveryTerminalEvent: SSEEvent | null = null;
    let deliveryFinalized = false;
    let deliveryProtocolError: string | null = null;
    const failDeliveryProtocol = (message: string): never => {
        deliveryProtocolError = message;
        throw new Error(message);
    };
    const deliverySequence = (event: SSEEvent, label: string): number => {
        if (!Number.isSafeInteger(event.event_seq) || (event.event_seq ?? 0) <= 0) {
            return failDeliveryProtocol(`${label} 缺少有效的持久化事件序号，请重新加载本次行程。`);
        }
        return event.event_seq!;
    };
    const finalizeDeliveryIfComplete = () => {
        if (deliveryFinalized || !deliveryReadyEvent || !deliveryTerminalEvent)
            return;
        const readySequence = deliverySequence(deliveryReadyEvent, '旅行交付事件');
        const terminalSequence = deliverySequence(deliveryTerminalEvent, '旅行终态事件');
        if (terminalSequence <= readySequence
            || deliveryTerminalEvent.status !== 'completed'
            || deliveryTerminalEvent.run_id !== deliveryReadyEvent.run_id
            || deliveryTerminalEvent.bundle_id !== deliveryReadyEvent.bundle_id) {
            failDeliveryProtocol('行程已更新，请重新加载本次行程。');
        }
        onFinalized(deliveryTerminalEvent);
        deliveryFinalized = true;
    };
    const acceptDeliveryReady = (event: SSEEvent) => {
        const sequence = deliverySequence(event, '旅行交付事件');
        const bundle = event.bundle;
        if (!isPublicDeliveryBundle(bundle)) {
            return failDeliveryProtocol('行程已更新，请重新加载本次行程。');
        }
        if (!event.manifest
            || event.bundle_id !== bundle.manifest.bundle_id
            || event.run_id !== bundle.manifest.run_id
            || event.manifest.bundle_id !== bundle.manifest.bundle_id
            || canonicalJson(event.manifest) !== canonicalJson(bundle.manifest)) {
            failDeliveryProtocol('行程已更新，请重新加载本次行程。');
        }
        if (deliveryReadyEvent) {
            const existingSequence = deliverySequence(deliveryReadyEvent, '旅行交付事件');
            if (existingSequence !== sequence
                || deliveryReadyEvent.run_id !== event.run_id
                || deliveryReadyEvent.bundle_id !== event.bundle_id
                || canonicalJson(deliveryReadyEvent.bundle) !== canonicalJson(bundle)) {
                failDeliveryProtocol('收到互相冲突的旅行交付事件，请重新加载本次行程。');
            }
            return;
        }
        deliveryReadyEvent = event;
        confirmedDeliveryBundle = bundle;
        onReady(bundle);
        finalizeDeliveryIfComplete();
    };
    const acceptDeliveryTerminal = (event: SSEEvent) => {
        const sequence = deliverySequence(event, '旅行终态事件');
        if (event.status !== 'completed' || !event.bundle_id || !event.run_id) {
            failDeliveryProtocol('旅行交付未进入完整终态，请重新加载本次行程。');
        }
        if (deliveryTerminalEvent) {
            const existingSequence = deliverySequence(deliveryTerminalEvent, '旅行终态事件');
            if (existingSequence !== sequence
                || deliveryTerminalEvent.run_id !== event.run_id
                || deliveryTerminalEvent.bundle_id !== event.bundle_id) {
                failDeliveryProtocol('收到互相冲突的旅行终态事件，请重新加载本次行程。');
            }
            return;
        }
        deliveryTerminalEvent = event;
        finalizeDeliveryIfComplete();
    };
    const recoverDeliveryTerminal = async () => {
        if (!deliveryReadyEvent || deliveryFinalized || !identity.runId)
            return;
        const readySequence = deliverySequence(deliveryReadyEvent, '旅行交付事件');
        let window = await getTripRunEventWindow(identity.runId, {
            sessionId: identity.sessionId,
            afterSequence: readySequence,
        });
        if (window.window_expired) {
            window = await getTripRunEventWindow(identity.runId, {
                sessionId: identity.sessionId,
                afterSequence: Math.max(0, window.replay_floor_sequence - 1),
            });
        }
        if (window.run_status !== 'completed') {
            throw new Error('旅行交付终态尚未持久化');
        }
        const matching = window.events.filter((event) => (event.event_type === 'run.terminal'
            && event.payload.status === 'completed'
            && event.payload.bundle_id === deliveryReadyEvent?.bundle_id));
        if (matching.length !== 1) {
            throw new Error('旅行交付终态事件缺失或重复');
        }
        const terminal = matching[0];
        acceptDeliveryTerminal({
            type: 'run_terminal',
            run_id: terminal.run_id,
            event_id: terminal.event_id == null ? undefined : String(terminal.event_id),
            event_seq: terminal.sequence,
            bundle_id: String(terminal.payload.bundle_id),
            status: 'completed',
        });
    };
    return { acceptDeliveryReady, acceptDeliveryTerminal, recoverDeliveryTerminal,
        get confirmedBundle() { return confirmedDeliveryBundle; },
        get readyEvent() { return deliveryReadyEvent; },
        get finalized() { return deliveryFinalized; },
        get error() { return deliveryProtocolError; },
    };
}
