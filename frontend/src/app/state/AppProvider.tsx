import { useReducer } from "react";
import { appReducer } from "./appReducer";
import { initialState } from "./initialState";
import { type ActiveStreamHandle, type SessionRuntimeSnapshot } from "../session/runtimeSnapshot";
import { type AppState } from "./state";
import { type PendingFollowups } from "../session/pendingFollowups";
import { AppContext } from "./AppContext";
import React, { type ReactNode } from 'react';
import { useIsMobileViewport } from '../../hooks/useMediaQuery';
export const AppProvider: React.FC<{
    children: ReactNode;
}> = ({ children }) => {
    const [state, dispatch] = useReducer(appReducer, initialState);
    const activeStreamsRef = React.useRef<Map<string, ActiveStreamHandle>>(new Map());
    const currentStateRef = React.useRef<AppState>(state);
    const sessionRuntimeCacheRef = React.useRef<Map<string, SessionRuntimeSnapshot>>(new Map());
    const [pendingFollowups, setPendingFollowupsState] = React.useState<PendingFollowups>({});
    const pendingFollowupsRef = React.useRef(pendingFollowups);
    const setPendingFollowups = React.useCallback<React.Dispatch<React.SetStateAction<PendingFollowups>>>((action) => {
        const next = typeof action === 'function' ? action(pendingFollowupsRef.current) : action;
        pendingFollowupsRef.current = next;
        setPendingFollowupsState(next);
    }, []);
    React.useEffect(() => {
        currentStateRef.current = state;
    }, [state]);
    const mobileViewportRef = React.useRef<boolean | null>(null);
    const isMobile = useIsMobileViewport();
    React.useEffect(() => {
        if (isMobile && mobileViewportRef.current === false) {
            dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true });
        }
        mobileViewportRef.current = isMobile;
    }, [isMobile]);
    const value = React.useMemo(() => ({
        state,
        dispatch,
        activeStreamsRef,
        currentStateRef,
        sessionRuntimeCacheRef,
        pendingFollowups,
        setPendingFollowups,
        pendingFollowupsRef,
    }), [state, pendingFollowups, setPendingFollowups]);
    return (<AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>);
};
