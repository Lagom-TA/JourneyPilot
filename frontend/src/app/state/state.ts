import { type TripRunStatus } from "../../features/travel/types/runs";
import { type PublicDeliveryBundle } from "../../features/travel/types/delivery";
import { type SessionRuntimeSnapshot } from "../session/runtimeSnapshot";
import { type ChatState, type ChatAction } from "../../features/chat/model/state";
import { type TravelState, type TravelAction } from "../../features/travel/model/state";
export type ActiveView = 'chat' | 'trips' | 'knowledge-base' | 'presets' | 'user-preferences';
const VALID_ACTIVE_VIEWS: ActiveView[] = [
    'chat',
    'trips',
    'knowledge-base',
    'presets',
    'user-preferences',
];
export function isActiveView(value: string | null | undefined): value is ActiveView {
    return value != null && VALID_ACTIVE_VIEWS.includes(value as ActiveView);
}
export interface AppState extends ChatState, TravelState {
    activeView: ActiveView;
    sidebarCollapsed: boolean;
    currentSessionId: string | null;
    canvasOpen: boolean;
    mobileCanvasOpen: boolean;
    activePresetId: string | null;
    activePresetName: string | null;
}
export type AppAction = ChatAction | TravelAction | {
    type: 'SET_ACTIVE_VIEW';
    payload: ActiveView;
} | {
    type: 'SET_SIDEBAR_COLLAPSED';
    payload: boolean;
} | {
    type: 'SET_SESSION_ID';
    payload: string | null;
} | {
    type: 'SET_CURRENT_TRIP_RUN';
    payload: {
        runId: string | null;
        source?: AppState['tripRunSource'];
        status?: TripRunStatus | null;
        readOnly?: boolean;
    };
} | {
    type: 'SET_TRIP_RUN_STATUS';
    payload: TripRunStatus | null;
} | {
    type: 'CONFIRM_DELIVERY_BUNDLE';
    payload: PublicDeliveryBundle;
} | {
    type: 'RESTORE_SESSION_RUNTIME';
    payload: SessionRuntimeSnapshot;
} | {
    type: 'CLEAR_TRACE';
} | {
    type: 'SET_MOBILE_CANVAS_OPEN';
    payload: boolean;
} | {
    type: 'MARK_PENDING_DECISIONS_CANCELLED';
} | {
    type: 'SET_ACTIVE_PRESET';
    payload: {
        id: string;
        name: string;
    } | null;
} | {
    type: 'CLEAR_CHAT';
};
